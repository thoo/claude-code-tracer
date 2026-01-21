"""SQL query templates for DuckDB session analytics.

Placeholders:
- {path}: Session JSON file path (for direct read_json_auto queries)
- {source}: Query source - either a view name or read_json_auto() expression
- {sort_dir}: ASC or DESC for ordering
- {offset}, {limit}: Pagination parameters
- {type_filter}, {where_clause}: Optional filtering clauses
"""

# Common read_json_auto options:
# - maximum_object_size: 100MB to handle large session files
# - ignore_errors: Skip malformed entries instead of failing
# - union_by_name: Merge schemas across rows (handles missing columns with NULL)
#
# NOTE: We intentionally do NOT use the `columns=` parameter because:
# 1. It restricts which columns are read (excluding any not listed)
# 2. Declaring `message` as JSON prevents nested access (e.g., message.usage.input_tokens)
# Instead, we rely on union_by_name=true and SQL-level NULL checks for missing columns.
_JSON_OPTS = "maximum_object_size=104857600, ignore_errors=true, union_by_name=true"

# Helper for robust content string extraction
# CAST(to_json(...) AS VARCHAR) ensures we always get a valid JSON string
# - Lists/Structs become '[{...}]' (valid JSON)
# - Strings become '"..."' (quoted JSON string)
# This handles the case where DuckDB might infer message.content as LIST(STRUCT) or VARCHAR unpredictably.
_CONTENT_AS_JSON_STR = "CAST(to_json(message.content) AS VARCHAR)"


def make_source_query(path: str) -> str:
    """Create a read_json_auto query source from a file path.

    Use this when you need to construct a source string for queries that use {source}.
    For session views, use get_session_view_query() from database.py instead.
    """
    return f"read_json_auto('{path}', {_JSON_OPTS})"


# Reusable SQL snippet for classifying user messages into subtypes
_USER_TYPE_CASE = f"""CASE
            WHEN type = 'user'
                 AND {_CONTENT_AS_JSON_STR} NOT LIKE '[{{{{"tool_use_id"%'
                 AND {_CONTENT_AS_JSON_STR} NOT LIKE '[{{{{"type":"tool_result"%'
                 AND ({_CONTENT_AS_JSON_STR} LIKE '"<command-name>%'
                      OR {_CONTENT_AS_JSON_STR} LIKE '"<local-command-caveat>%'
                      OR {_CONTENT_AS_JSON_STR} LIKE '"<local-command-stdout>%'
                      OR {_CONTENT_AS_JSON_STR} LIKE '"<user-prompt-submit-hook>%')
            THEN 'hook'
            WHEN type = 'user'
                 AND ({_CONTENT_AS_JSON_STR} LIKE '[{{{{"tool_use_id"%'
                      OR {_CONTENT_AS_JSON_STR} LIKE '[{{{{"type":"tool_result"%')
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
        unnest(from_json(CAST(message.content AS JSON), '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR"}}}}]')) as item,
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
        unnest(from_json(CAST(message.content AS JSON), '[{{{{"tool_use_id": "VARCHAR", "is_error": "BOOLEAN"}}}}]')) as result_item,
        CAST(timestamp AS TIMESTAMP) as tool_result_ts
    FROM read_json_auto('{{path}}', {_JSON_OPTS})
    WHERE type = 'user'
      AND ({_CONTENT_AS_JSON_STR} LIKE '[{{{{"tool_use_id"%'
           OR {_CONTENT_AS_JSON_STR} LIKE '[{{{{"type":"tool_result"%')
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
        from_json(CAST(message.content AS JSON), '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}}}]') as content_list,
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
        from_json(CAST(message.content AS JSON), '[{{{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}}}]') as content_list,
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
        from_json(CAST(message.content AS JSON), '[{{{{"type": "VARCHAR", "name": "VARCHAR", "input": "JSON"}}}}]') as content_list
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
    SELECT {_CONTENT_AS_JSON_STR} as content
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
        {_CONTENT_AS_JSON_STR} as content_str
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
      AND (content_str LIKE '"<command-name>%'
           OR content_str LIKE '"<local-command-caveat>%'
           OR content_str LIKE '"<local-command-stdout>%'
           OR content_str LIKE '"<user-prompt-submit-hook>%')
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
      AND content_str NOT LIKE '"<command-name>%'
      AND content_str NOT LIKE '"<local-command-caveat>%'
      AND content_str NOT LIKE '"<local-command-stdout>%'
      AND content_str NOT LIKE '"<user-prompt-submit-hook>%'
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
  AND ({_CONTENT_AS_JSON_STR} LIKE '%"is_error": true%'
       OR {_CONTENT_AS_JSON_STR} LIKE '%"is_error":true%')
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

# ============================================================================
# SOURCE-BASED QUERIES (Priority 2.3 - Session View Optimization)
# ============================================================================
# These queries use {source} placeholder instead of read_json_auto, allowing
# callers to pass either a view name (for cached session data) or a
# read_json_auto expression. This enables session view reuse across
# multiple queries for the same session.

MESSAGES_COMPREHENSIVE_QUERY_V2 = """
WITH base_messages AS (
    SELECT
        uuid,
        type,
        timestamp,
        message,
        CAST(message AS JSON) as message_json,
        sessionId as session_id,
        CAST(to_json(message.content) AS VARCHAR) as content_str
    FROM {source}
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
    FROM {source}
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
        unnest(from_json(content_str, '[{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}]')) as tool_item
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
                SELECT unnest(from_json(content_str, '[{{"type": "VARCHAR", "name": "VARCHAR"}}]')) as item
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
      AND content_str NOT LIKE '[{{"tool_use_id"%'
      AND content_str NOT LIKE '[{{"type":"tool_result"%'
      AND (content_str LIKE '"<command-name>%'
           OR content_str LIKE '"<local-command-caveat>%'
           OR content_str LIKE '"<local-command-stdout>%'
           OR content_str LIKE '"<user-prompt-submit-hook>%')
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
      AND content_str NOT LIKE '[{{"tool_use_id"%'
      AND content_str NOT LIKE '[{{"type":"tool_result"%'
      AND content_str NOT LIKE '"<command-name>%'
      AND content_str NOT LIKE '"<local-command-caveat>%'
      AND content_str NOT LIKE '"<local-command-stdout>%'
      AND content_str NOT LIKE '"<user-prompt-submit-hook>%'
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
      AND (content_str LIKE '[{{"tool_use_id"%' OR content_str LIKE '[{{"type":"tool_result"%')
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
    ROW_NUMBER() OVER (ORDER BY timestamp {sort_dir}) as row_num
FROM all_unified
{where_clause}
"""

TOOL_NAMES_LIST_QUERY_V2 = """
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR"}}]') as content_list
    FROM {source}
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

ERROR_COUNT_QUERY_V2 = """
SELECT COUNT(*) as error_count
FROM {source}
WHERE type = 'user'
  AND (CAST(message.content AS VARCHAR) LIKE '%"is_error": true%'
       OR CAST(message.content AS VARCHAR) LIKE '%"is_error":true%')
"""

TOKEN_USAGE_QUERY_V2 = """
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM {source}
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

TOKEN_USAGE_BY_MODEL_QUERY_V2 = """
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        message.model as model,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM {source}
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

MESSAGE_COUNT_QUERY_V2 = """
SELECT
    COUNT(*) as total_count,
    COUNT(CASE WHEN type = 'assistant' THEN 1 END) as assistant_count,
    COUNT(CASE WHEN type = 'user' THEN 1 END) as user_count
FROM {source}
WHERE type IN ('assistant', 'user')
"""

TOOL_USAGE_QUERY_V2 = """
WITH tool_uses AS (
    SELECT
        unnest(from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR"}}]')) as item,
        CAST(timestamp AS TIMESTAMP) as tool_use_ts
    FROM {source}
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
        unnest(from_json(message.content, '[{{"tool_use_id": "VARCHAR", "is_error": "BOOLEAN"}}]')) as result_item,
        CAST(timestamp AS TIMESTAMP) as tool_result_ts
    FROM {source}
    WHERE type = 'user'
      AND (CAST(message.content AS VARCHAR) LIKE '[{{"tool_use_id"%'
           OR CAST(message.content AS VARCHAR) LIKE '[{{"type":"tool_result"%')
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

SESSION_TIMERANGE_QUERY_V2 = """
SELECT
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time
FROM {source}
"""

SESSION_STATUS_QUERY_V2 = """
WITH last_msg AS (
    SELECT CAST(message.content AS VARCHAR) as content
    FROM {source}
    WHERE type IN ('user', 'assistant')
    ORDER BY timestamp DESC
    LIMIT 1
),
summary_check AS (
    SELECT COUNT(*) > 0 as has_summary
    FROM {source}
    WHERE type = 'summary'
)
SELECT
    (SELECT has_summary FROM summary_check) as has_summary,
    (SELECT content FROM last_msg) as last_content
"""

USER_COMMANDS_QUERY_V2 = """
WITH entries AS (
    SELECT
        uuid,
        type,
        timestamp,
        message,
        LEAD(type) OVER (ORDER BY timestamp) as next_type
    FROM {source}
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

SUBAGENT_CALLS_WITH_AGENT_ID_QUERY_V2 = """
WITH task_tool_calls AS (
    SELECT
        unnest(from_json(CAST(message.content AS VARCHAR), '[{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}]')) as tool_item,
        timestamp
    FROM {source}
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
    FROM {source}
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

SKILL_CALLS_QUERY_V2 = """
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}]') as content_list,
        timestamp
    FROM {source}
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

CODE_CHANGES_QUERY_V2 = """
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR", "input": "JSON"}}]') as content_list
    FROM {source}
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


# ============================================================================
# GLOB-BASED AGGREGATE QUERIES (Priority 2 Optimizations)
# ============================================================================
# These queries use DuckDB's glob patterns to aggregate across multiple files
# in a single query, replacing N+1 query patterns.

# Aggregate token usage and metrics across all sessions in all projects
# Uses glob pattern like '~/.claude/projects/*/*.jsonl'
AGGREGATE_ALL_PROJECTS_QUERY = f"""
WITH file_data AS (
    SELECT
        filename,
        regexp_extract(filename, '.*/projects/([^/]+)/[^/]+\.jsonl$', 1) as project_hash,
        regexp_extract(filename, '.*/projects/[^/]+/([^/]+)\.jsonl$', 1) as session_id,
        type,
        timestamp,
        message
    FROM read_json_auto(
        '{{glob_pattern}}',
        filename=true,
        {_JSON_OPTS}
    )
    WHERE regexp_extract(filename, '.*/projects/[^/]+/([^/]+)\.jsonl$', 1) NOT LIKE 'agent-%'
),
deduplicated AS (
    SELECT DISTINCT ON (project_hash, session_id, message.id)
        project_hash,
        session_id,
        message.model as model,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read,
        timestamp
    FROM file_data
    WHERE type = 'assistant'
      AND message.usage IS NOT NULL
      AND message.id IS NOT NULL
),
project_metrics AS (
    SELECT
        project_hash,
        COUNT(DISTINCT session_id) as session_count,
        COALESCE(SUM(input_tokens), 0) as total_input_tokens,
        COALESCE(SUM(output_tokens), 0) as total_output_tokens,
        COALESCE(SUM(cache_creation), 0) as total_cache_creation,
        COALESCE(SUM(cache_read), 0) as total_cache_read,
        MIN(timestamp) as first_activity,
        MAX(timestamp) as last_activity,
        array_agg(DISTINCT model) FILTER (WHERE model IS NOT NULL) as models_used
    FROM deduplicated
    GROUP BY project_hash
)
SELECT * FROM project_metrics
"""

# Aggregate token usage for a single project across all its sessions
AGGREGATE_PROJECT_SESSIONS_QUERY = f"""
WITH file_data AS (
    SELECT
        filename,
        regexp_extract(filename, '.*/([^/]+)\.jsonl$', 1) as session_id,
        type,
        timestamp,
        message
    FROM read_json_auto(
        '{{glob_pattern}}',
        filename=true,
        {_JSON_OPTS}
    )
    WHERE regexp_extract(filename, '.*/([^/]+)\.jsonl$', 1) NOT LIKE 'agent-%'
),
deduplicated AS (
    SELECT DISTINCT ON (session_id, message.id)
        session_id,
        message.model as model,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read,
        timestamp
    FROM file_data
    WHERE type = 'assistant'
      AND message.usage IS NOT NULL
      AND message.id IS NOT NULL
)
SELECT
    COUNT(DISTINCT session_id) as session_count,
    COALESCE(SUM(input_tokens), 0) as total_input_tokens,
    COALESCE(SUM(output_tokens), 0) as total_output_tokens,
    COALESCE(SUM(cache_creation), 0) as total_cache_creation,
    COALESCE(SUM(cache_read), 0) as total_cache_read,
    MIN(timestamp) as first_activity,
    MAX(timestamp) as last_activity
FROM deduplicated
"""

# Token usage by model across multiple files (for accurate cost calculation)
TOKEN_USAGE_BY_MODEL_GLOB_QUERY = f"""
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        message.model as model,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM read_json_auto({{paths}}, {_JSON_OPTS})
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

# Batch query for session summaries - get multiple sessions at once
BATCH_SESSION_SUMMARIES_QUERY = f"""
WITH file_data AS (
    SELECT
        filename,
        regexp_extract(filename, '.*/([^/]+)\.jsonl$', 1) as session_id,
        type,
        timestamp,
        message
    FROM read_json_auto(
        '{{glob_pattern}}',
        filename=true,
        {_JSON_OPTS}
    )
    WHERE regexp_extract(filename, '.*/([^/]+)\.jsonl$', 1) NOT LIKE 'agent-%'
),
token_usage AS (
    SELECT DISTINCT ON (session_id, message.id)
        session_id,
        message.model as model,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM file_data
    WHERE type = 'assistant'
      AND message.usage IS NOT NULL
      AND message.id IS NOT NULL
),
session_tokens AS (
    SELECT
        session_id,
        COALESCE(SUM(input_tokens), 0) as input_tokens,
        COALESCE(SUM(output_tokens), 0) as output_tokens,
        COALESCE(SUM(cache_creation), 0) as cache_creation,
        COALESCE(SUM(cache_read), 0) as cache_read
    FROM token_usage
    GROUP BY session_id
),
session_model_costs AS (
    SELECT
        session_id,
        model,
        COALESCE(SUM(input_tokens), 0) as model_input,
        COALESCE(SUM(output_tokens), 0) as model_output,
        COALESCE(SUM(cache_creation), 0) as model_cache_creation,
        COALESCE(SUM(cache_read), 0) as model_cache_read
    FROM token_usage
    WHERE model IS NOT NULL
    GROUP BY session_id, model
),
message_counts AS (
    SELECT
        session_id,
        COUNT(*) as message_count
    FROM file_data
    WHERE type IN ('assistant', 'user')
    GROUP BY session_id
),
time_ranges AS (
    SELECT
        session_id,
        MIN(timestamp) as start_time,
        MAX(timestamp) as end_time
    FROM file_data
    GROUP BY session_id
),
error_counts AS (
    SELECT
        session_id,
        COUNT(*) as error_count
    FROM file_data
    WHERE type = 'user'
      AND (CAST(message.content AS VARCHAR) LIKE '%"is_error": true%'
           OR CAST(message.content AS VARCHAR) LIKE '%"is_error":true%')
    GROUP BY session_id
),
status_check AS (
    SELECT DISTINCT ON (session_id)
        session_id,
        type = 'summary' as has_summary
    FROM file_data
    WHERE type = 'summary'
)
SELECT
    t.session_id,
    st.input_tokens,
    st.output_tokens,
    st.cache_creation,
    st.cache_read,
    mc.message_count,
    tr.start_time,
    tr.end_time,
    COALESCE(ec.error_count, 0) as error_count,
    COALESCE(sc.has_summary, false) as has_summary
FROM time_ranges t
LEFT JOIN session_tokens st ON t.session_id = st.session_id
LEFT JOIN message_counts mc ON t.session_id = mc.session_id
LEFT JOIN error_counts ec ON t.session_id = ec.session_id
LEFT JOIN status_check sc ON t.session_id = sc.session_id
"""

# Error count across multiple files
ERROR_COUNT_GLOB_QUERY = f"""
SELECT COUNT(*) as error_count
FROM read_json_auto({{paths}}, {_JSON_OPTS})
WHERE type = 'user'
  AND (CAST(to_json(message.content) AS VARCHAR) LIKE '%"is_error": true%'
       OR CAST(to_json(message.content) AS VARCHAR) LIKE '%"is_error":true%')
"""
