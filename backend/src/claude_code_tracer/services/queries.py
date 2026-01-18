"""SQL query templates for DuckDB session analytics.

Placeholders:
- {path}: Session JSON file path
- {sort_dir}: ASC or DESC for ordering
- {offset}, {limit}: Pagination parameters
- {type_filter}, {where_clause}: Optional filtering clauses
"""

# Common read_json_auto options (100MB max object size, skip malformed entries, merge schemas)
_JSON_OPTS = "maximum_object_size=104857600, ignore_errors=true, union_by_name=true"

# Reusable SQL snippet for classifying user messages into subtypes
_USER_TYPE_CASE = """CASE
            WHEN type = 'user'
                 AND CAST(message.content AS VARCHAR) NOT LIKE '[{{{{"tool_use_id"%'
                 AND CAST(message.content AS VARCHAR) NOT LIKE '[{{{{"type":"tool_result"%'
                 AND (CAST(message.content AS VARCHAR) LIKE '<command-name>%'
                      OR CAST(message.content AS VARCHAR) LIKE '<local-command-caveat>%'
                      OR CAST(message.content AS VARCHAR) LIKE '<local-command-stdout>%'
                      OR CAST(message.content AS VARCHAR) LIKE '<user-prompt-submit-hook>%')
            THEN 'hook'
            WHEN type = 'user'
                 AND (CAST(message.content AS VARCHAR) LIKE '[{{{{"tool_use_id"%'
                      OR CAST(message.content AS VARCHAR) LIKE '[{{{{"type":"tool_result"%')
            THEN 'tool_result'
            ELSE type
        END"""

LOAD_SESSION = f"""
SELECT *
FROM read_json_auto('{{path}}', {_JSON_OPTS})
"""

TOOL_USAGE_QUERY = f"""
WITH tool_uses AS (
    SELECT
        unnest(from_json(message.content, '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR"}}}}]')) as item,
        CAST(timestamp AS TIMESTAMP) as tool_use_ts
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
),
tool_use_list AS (
    SELECT
        item.id as tool_use_id,
        item.name as tool_name,
        tool_use_ts
    FROM tool_uses
    WHERE item.type = 'tool_use' AND item.id IS NOT NULL
),
tool_results AS (
    SELECT
        unnest(from_json(message.content, '[{{{{"tool_use_id": "VARCHAR", "is_error": "BOOLEAN"}}}}]')) as result_item,
        CAST(timestamp AS TIMESTAMP) as tool_result_ts
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'user'
      AND (CAST(message.content AS VARCHAR) LIKE '[{{{{"tool_use_id"%'
           OR CAST(message.content AS VARCHAR) LIKE '[{{{{"type":"tool_result"%')
),
tool_result_list AS (
    SELECT
        result_item.tool_use_id as tool_use_id,
        COALESCE(result_item.is_error, false) as is_error,
        tool_result_ts
    FROM tool_results
    WHERE result_item.tool_use_id IS NOT NULL
),
matched AS (
    SELECT
        tu.tool_name,
        tu.tool_use_ts,
        tr.tool_result_ts,
        COALESCE(tr.is_error, false) as is_error,
        CASE
            WHEN tr.tool_result_ts IS NOT NULL AND tu.tool_use_ts IS NOT NULL
            THEN EXTRACT(EPOCH FROM (tr.tool_result_ts - tu.tool_use_ts))
            ELSE NULL
        END as duration_seconds
    FROM tool_use_list tu
    LEFT JOIN tool_result_list tr ON tu.tool_use_id = tr.tool_use_id
)
SELECT
    tool_name,
    COUNT(*) as count,
    COALESCE(AVG(duration_seconds), 0) as avg_duration_seconds,
    SUM(CASE WHEN is_error THEN 1 ELSE 0 END) as error_count
FROM matched
GROUP BY tool_name
ORDER BY count DESC
"""

TOKEN_USAGE_QUERY = f"""
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
      AND message.usage IS NOT NULL
      AND message.id IS NOT NULL
)
SELECT
    COALESCE(SUM(input_tokens), 0) as input_tokens,
    COALESCE(SUM(output_tokens), 0) as output_tokens,
    COALESCE(SUM(cache_creation), 0) as cache_creation,
    COALESCE(SUM(cache_read), 0) as cache_read
FROM deduplicated
"""

MESSAGE_COUNT_QUERY = f"""
SELECT
    COUNT(*) as total_count,
    COUNT(CASE WHEN type = 'assistant' THEN 1 END) as assistant_count,
    COUNT(CASE WHEN type = 'user' THEN 1 END) as user_count
FROM read_json_auto('{{path}}', {_JSON_OPTS})
WHERE type IN ('assistant', 'user')
"""

MESSAGES_PAGINATED_QUERY = f"""
WITH all_messages AS (
    SELECT
        uuid,
        type,
        timestamp,
        message,
        CASE WHEN type = 'assistant' THEN message.model ELSE NULL END as model,
        CASE WHEN type = 'assistant' THEN message.usage ELSE NULL END as usage,
        sessionId as session_id,
        ROW_NUMBER() OVER (ORDER BY timestamp {{sort_dir}}) as row_num
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type IN ('assistant', 'user')
    {{type_filter}}
)
SELECT * FROM all_messages
WHERE row_num > {{offset}}
LIMIT {{limit}}
"""

ERROR_MESSAGES_QUERY = f"""
WITH user_entries AS (
    SELECT
        uuid,
        timestamp,
        message.content as content
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'user'
)
SELECT *
FROM user_entries
WHERE content IS NOT NULL
"""

SUBAGENT_CALLS_QUERY = f"""
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}}}]') as content_list,
        timestamp
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
),
task_calls AS (
    SELECT unnest(content_list) as content_item, timestamp
    FROM parsed
)
SELECT
    content_item.id as tool_use_id,
    content_item.input.subagent_type as subagent_type,
    content_item.input.description as description,
    content_item.input.prompt as prompt,
    timestamp
FROM task_calls
WHERE content_item.type = 'tool_use'
  AND content_item.name = 'Task'
"""

SKILL_CALLS_QUERY = f"""
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}}}]') as content_list,
        timestamp
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
),
skill_calls AS (
    SELECT unnest(content_list) as content_item, timestamp
    FROM parsed
)
SELECT
    content_item.id as tool_use_id,
    content_item.input.skill as skill_name,
    content_item.input.args as skill_args,
    timestamp
FROM skill_calls
WHERE content_item.type = 'tool_use'
  AND content_item.name = 'Skill'
"""

CODE_CHANGES_QUERY = f"""
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{{{"type": "VARCHAR", "name": "VARCHAR", "input": "JSON"}}}}]') as content_list
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
),
edit_calls AS (
    SELECT unnest(content_list) as content_item
    FROM parsed
)
SELECT
    content_item.input.file_path as file_path,
    content_item.input.old_string as old_string,
    content_item.input.new_string as new_string,
    content_item.input.content as write_content,
    content_item.name as operation
FROM edit_calls
WHERE content_item.type = 'tool_use'
  AND content_item.name IN ('Edit', 'Write')
"""

SESSION_TIMERANGE_QUERY = f"""
SELECT
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time
FROM read_json_auto('{{path}}', {_JSON_OPTS})
"""

SESSION_STATUS_QUERY = f"""
WITH last_msg AS (
    SELECT CAST(message.content AS VARCHAR) as content
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type IN ('user', 'assistant')
    ORDER BY timestamp DESC
    LIMIT 1
),
summary_check AS (
    SELECT COUNT(*) > 0 as has_summary
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'summary'
)
SELECT
    (SELECT has_summary FROM summary_check) as has_summary,
    (SELECT content FROM last_msg) as last_content
"""

MODELS_USED_QUERY = f"""
SELECT DISTINCT message.model as model
FROM read_json_auto('{{path}}', {_JSON_OPTS})
WHERE type = 'assistant' AND message.model IS NOT NULL
"""

TOKEN_USAGE_BY_MODEL_QUERY = f"""
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        message.model as model,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
      AND message.usage IS NOT NULL
      AND message.model IS NOT NULL
      AND message.id IS NOT NULL
)
SELECT
    model,
    COALESCE(SUM(input_tokens), 0) as input_tokens,
    COALESCE(SUM(output_tokens), 0) as output_tokens,
    COALESCE(SUM(cache_creation), 0) as cache_creation,
    COALESCE(SUM(cache_read), 0) as cache_read
FROM deduplicated
GROUP BY model
"""

USER_COMMANDS_QUERY = f"""
WITH entries AS (
    SELECT
        uuid,
        type,
        timestamp,
        message,
        LEAD(type) OVER (ORDER BY timestamp) as next_type
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type IN ('user', 'assistant')
)
SELECT
    uuid,
    timestamp,
    message.content as content,
    next_type = 'user' as followed_by_interruption
FROM entries
WHERE type = 'user'
  AND message.role = 'user'
  AND typeof(message.content) = 'VARCHAR'
  AND length(message.content) > 0
ORDER BY timestamp
"""

DAILY_METRICS_QUERY = f"""
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        timestamp,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
      AND message.usage IS NOT NULL
      AND message.id IS NOT NULL
      AND timestamp >= '{{start_date}}'
      AND timestamp <= '{{end_date}}'
)
SELECT
    date_trunc('day', timestamp) as date,
    SUM(input_tokens) as input_tokens,
    SUM(output_tokens) as output_tokens,
    SUM(cache_creation) as cache_creation,
    SUM(cache_read) as cache_read,
    COUNT(*) as message_count
FROM deduplicated
GROUP BY date_trunc('day', timestamp)
ORDER BY date
"""

MESSAGES_COMPREHENSIVE_QUERY = f"""
WITH base_messages AS (
    SELECT
        uuid,
        type,
        timestamp,
        message,
        CAST(message AS JSON) as message_json,
        sessionId as session_id,
        CAST(message.content AS VARCHAR) as content_str
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type IN ('assistant', 'user')
),
all_progress_entries AS (
    SELECT
        uuid,
        type,
        timestamp,
        data,
        sessionId as session_id,
        toolUseID as tool_use_id,
        parentToolUseID as parent_tool_use_id,
        json_extract_string(data, '$.agentId') as agent_id,
        ROW_NUMBER() OVER (PARTITION BY json_extract_string(data, '$.agentId') ORDER BY timestamp ASC) as rn
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'progress'
      AND json_extract_string(data, '$.type') = 'agent_progress'
),
progress_entries AS (
    SELECT uuid, type, timestamp, data, session_id, tool_use_id, parent_tool_use_id, agent_id
    FROM all_progress_entries
    WHERE rn = 1
),
task_tool_calls AS (
    SELECT
        uuid,
        timestamp,
        session_id,
        unnest(from_json(content_str, '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}}}]')) as tool_item
    FROM base_messages
    WHERE type = 'assistant'
),
task_tool_details AS (
    SELECT
        tool_item.id as tool_id,
        tool_item.type as tool_type,
        tool_item.name as tool_name,
        json_extract_string(tool_item.input, '$.subagent_type') as subagent_type,
        json_extract_string(tool_item.input, '$.description') as description
    FROM task_tool_calls
    WHERE tool_item.type = 'tool_use' AND tool_item.name = 'Task'
),
subagent_messages AS (
    SELECT
        p.uuid,
        'subagent' as msg_type,
        p.timestamp,
        json_object(
            'agentId', json_extract_string(p.data, '$.agentId'),
            'subagent_type', COALESCE(t.subagent_type, 'unknown'),
            'description', t.description,
            'prompt', json_extract_string(p.data, '$.prompt')
        ) as message,
        NULL as model,
        NULL as usage,
        p.session_id,
        COALESCE(t.subagent_type, '') as tool_names,
        false as is_error
    FROM progress_entries p
    LEFT JOIN task_tool_details t ON p.parent_tool_use_id = t.tool_id
),
assistant_messages AS (
    SELECT
        uuid,
        'assistant' as msg_type,
        timestamp,
        message,
        json_extract_string(message_json, '$.model') as model,
        json_extract(message_json, '$.usage') as usage,
        session_id,
        COALESCE((
            SELECT string_agg(item.name, ', ')
            FROM (
                SELECT unnest(from_json(content_str, '[{{{{"type": "VARCHAR", "name": "VARCHAR"}}}}]')) as item
            )
            WHERE item.type = 'tool_use' AND item.name != 'Task'
        ), '') as tool_names,
        false as is_error
    FROM base_messages
    WHERE type = 'assistant'
),
hook_messages AS (
    SELECT
        uuid,
        'hook' as msg_type,
        timestamp,
        message,
        NULL as model,
        NULL as usage,
        session_id,
        '' as tool_names,
        false as is_error
    FROM base_messages
    WHERE type = 'user'
      AND content_str NOT LIKE '[{{{{"tool_use_id"%'
      AND content_str NOT LIKE '[{{{{"type":"tool_result"%'
      AND (content_str LIKE '<command-name>%'
           OR content_str LIKE '<local-command-caveat>%'
           OR content_str LIKE '<local-command-stdout>%'
           OR content_str LIKE '<user-prompt-submit-hook>%')
),
user_prompt_messages AS (
    SELECT
        uuid,
        'user' as msg_type,
        timestamp,
        message,
        NULL as model,
        NULL as usage,
        session_id,
        '' as tool_names,
        false as is_error
    FROM base_messages
    WHERE type = 'user'
      AND content_str NOT LIKE '[{{{{"tool_use_id"%'
      AND content_str NOT LIKE '[{{{{"type":"tool_result"%'
      AND content_str NOT LIKE '<command-name>%'
      AND content_str NOT LIKE '<local-command-caveat>%'
      AND content_str NOT LIKE '<local-command-stdout>%'
      AND content_str NOT LIKE '<user-prompt-submit-hook>%'
),
tool_result_messages AS (
    SELECT
        uuid,
        'tool_result' as msg_type,
        timestamp,
        message,
        NULL as model,
        NULL as usage,
        session_id,
        '' as tool_names,
        content_str LIKE '%"is_error": true%' OR content_str LIKE '%"is_error":true%' as is_error
    FROM base_messages
    WHERE type = 'user'
      AND (content_str LIKE '[{{{{"tool_use_id"%' OR content_str LIKE '[{{{{"type":"tool_result"%')
),
all_unified AS (
    SELECT * FROM assistant_messages
    UNION ALL
    SELECT * FROM subagent_messages
    UNION ALL
    SELECT * FROM hook_messages
    UNION ALL
    SELECT * FROM user_prompt_messages
    UNION ALL
    SELECT * FROM tool_result_messages
)
SELECT
    uuid,
    msg_type,
    timestamp,
    message,
    model,
    usage,
    session_id,
    tool_names,
    is_error,
    ROW_NUMBER() OVER (ORDER BY timestamp {{sort_dir}}) as row_num
FROM all_unified
{{where_clause}}
"""

TOOL_NAMES_LIST_QUERY = f"""
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{{{"type": "VARCHAR", "name": "VARCHAR"}}}}]') as content_list
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
),
tool_uses AS (
    SELECT unnest(content_list) as content_item
    FROM parsed
    WHERE content_list IS NOT NULL
)
SELECT
    content_item.name as tool_name,
    COUNT(*) as count
FROM tool_uses
WHERE content_item.type = 'tool_use'
GROUP BY content_item.name
ORDER BY count DESC
"""

ERROR_COUNT_QUERY = f"""
SELECT COUNT(*) as error_count
FROM read_json_auto('{{path}}', {_JSON_OPTS})
WHERE type = 'user'
  AND (CAST(message.content AS VARCHAR) LIKE '%"is_error": true%'
       OR CAST(message.content AS VARCHAR) LIKE '%"is_error":true%')
"""

SUBAGENT_CALLS_WITH_AGENT_ID_QUERY = f"""
WITH task_tool_calls AS (
    SELECT
        unnest(from_json(CAST(message.content AS VARCHAR), '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}}}]')) as tool_item,
        timestamp
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'assistant'
),
task_details AS (
    SELECT
        tool_item.id as tool_use_id,
        json_extract_string(tool_item.input, '$.subagent_type') as subagent_type,
        json_extract_string(tool_item.input, '$.description') as description,
        json_extract_string(tool_item.input, '$.prompt') as prompt,
        timestamp
    FROM task_tool_calls
    WHERE tool_item.type = 'tool_use' AND tool_item.name = 'Task'
),
agent_progress AS (
    SELECT DISTINCT ON (json_extract_string(data, '$.agentId'))
        json_extract_string(data, '$.agentId') as agent_id,
        parentToolUseID as parent_tool_use_id
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'progress'
      AND json_extract_string(data, '$.type') = 'agent_progress'
      AND json_extract_string(data, '$.agentId') IS NOT NULL
)
SELECT
    COALESCE(p.agent_id, t.tool_use_id) as agent_id,
    t.tool_use_id,
    t.subagent_type,
    t.description,
    t.prompt,
    t.timestamp
FROM task_details t
LEFT JOIN agent_progress p ON t.tool_use_id = p.parent_tool_use_id
WHERE t.tool_use_id IS NOT NULL
"""

MESSAGE_DETAIL_QUERY = f"""
WITH all_entries AS (
    SELECT
        uuid,
        type as raw_type,
        {_USER_TYPE_CASE} as type,
        timestamp,
        message,
        sessionId as session_id,
        cwd,
        ROW_NUMBER() OVER (ORDER BY timestamp ASC) as row_num
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type IN ('assistant', 'user')
),
total_count AS (
    SELECT COUNT(*) as total FROM all_entries
)
SELECT
    e.uuid,
    e.type,
    e.timestamp,
    e.message,
    e.session_id,
    e.cwd,
    e.row_num,
    t.total
FROM all_entries e, total_count t
WHERE e.uuid = '{{uuid}}'
"""

MESSAGE_INDEX_QUERY = f"""
WITH ordered_messages AS (
    SELECT
        uuid,
        ROW_NUMBER() OVER (ORDER BY timestamp ASC) as row_num
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type IN ('assistant', 'user')
)
SELECT row_num
FROM ordered_messages
WHERE uuid = '{{uuid}}'
"""

MESSAGE_BY_INDEX_QUERY = f"""
WITH ordered_messages AS (
    SELECT
        uuid,
        {_USER_TYPE_CASE} as type,
        timestamp,
        message,
        sessionId as session_id,
        cwd,
        ROW_NUMBER() OVER (ORDER BY timestamp ASC) as row_num
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type IN ('assistant', 'user')
),
total_count AS (
    SELECT COUNT(*) as total FROM ordered_messages
)
SELECT
    m.uuid,
    m.type,
    m.timestamp,
    m.message,
    m.session_id,
    m.cwd,
    m.row_num,
    t.total
FROM ordered_messages m, total_count t
WHERE m.row_num = {{index}}
"""
