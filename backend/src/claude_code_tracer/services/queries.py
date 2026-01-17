"""Reusable SQL query templates for DuckDB."""

LOAD_SESSION = """
SELECT *
FROM read_json_auto('{path}',
    maximum_object_size=104857600,
    ignore_errors=true
)
"""

TOOL_USAGE_QUERY = """
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR"}}]') as content_list
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
    WHERE type = 'assistant'
),
tool_uses AS (
    SELECT unnest(content_list) as content_item
    FROM parsed
)
SELECT
    content_item.name as tool_name,
    COUNT(*) as count
FROM tool_uses
WHERE content_item.type = 'tool_use'
GROUP BY content_item.name
ORDER BY count DESC
"""

TOKEN_USAGE_QUERY = """
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
    WHERE type = 'assistant' AND message.usage IS NOT NULL AND message.id IS NOT NULL
)
SELECT
    COALESCE(SUM(input_tokens), 0) as input_tokens,
    COALESCE(SUM(output_tokens), 0) as output_tokens,
    COALESCE(SUM(cache_creation), 0) as cache_creation,
    COALESCE(SUM(cache_read), 0) as cache_read
FROM deduplicated
"""

MESSAGE_COUNT_QUERY = """
SELECT
    COUNT(*) as total_count,
    COUNT(CASE WHEN type = 'assistant' THEN 1 END) as assistant_count,
    COUNT(CASE WHEN type = 'user' THEN 1 END) as user_count
FROM read_json_auto('{path}',
    maximum_object_size=104857600,
    ignore_errors=true
)
WHERE type IN ('assistant', 'user')
"""

MESSAGES_PAGINATED_QUERY = """
WITH all_messages AS (
    SELECT
        uuid,
        type,
        timestamp,
        message,
        CASE
            WHEN type = 'assistant' THEN message.model
            ELSE NULL
        END as model,
        CASE
            WHEN type = 'assistant' THEN message.usage
            ELSE NULL
        END as usage,
        sessionId as session_id,
        ROW_NUMBER() OVER (ORDER BY timestamp {sort_dir}) as row_num
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
    WHERE type IN ('assistant', 'user')
    {type_filter}
)
SELECT * FROM all_messages
WHERE row_num > {offset}
LIMIT {limit}
"""

ERROR_MESSAGES_QUERY = """
WITH user_entries AS (
    SELECT
        uuid,
        timestamp,
        message.content as content
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
    WHERE type = 'user'
)
SELECT *
FROM user_entries
WHERE content IS NOT NULL
"""

SUBAGENT_CALLS_QUERY = """
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}]') as content_list,
        timestamp
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
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

SKILL_CALLS_QUERY = """
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR", "id": "VARCHAR", "input": "JSON"}}]') as content_list,
        timestamp
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
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

CODE_CHANGES_QUERY = """
WITH parsed AS (
    SELECT
        from_json(message.content, '[{{"type": "VARCHAR", "name": "VARCHAR", "input": "JSON"}}]') as content_list
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
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

SESSION_TIMERANGE_QUERY = """
SELECT
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time
FROM read_json_auto('{path}',
    maximum_object_size=104857600,
    ignore_errors=true
)
"""

MODELS_USED_QUERY = """
SELECT DISTINCT message.model as model
FROM read_json_auto('{path}',
    maximum_object_size=104857600,
    ignore_errors=true
)
WHERE type = 'assistant' AND message.model IS NOT NULL
"""

TOKEN_USAGE_BY_MODEL_QUERY = """
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        message.model as model,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
    WHERE type = 'assistant' AND message.usage IS NOT NULL AND message.model IS NOT NULL AND message.id IS NOT NULL
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

USER_COMMANDS_QUERY = """
WITH entries AS (
    SELECT
        uuid,
        type,
        timestamp,
        message,
        LEAD(type) OVER (ORDER BY timestamp) as next_type
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
    WHERE type IN ('user', 'assistant')
)
SELECT
    uuid,
    timestamp,
    message.content as content,
    CASE WHEN next_type = 'user' THEN true ELSE false END as followed_by_interruption
FROM entries
WHERE type = 'user'
  AND message.role = 'user'
  AND typeof(message.content) = 'VARCHAR'
  AND length(message.content) > 0
ORDER BY timestamp
"""

DAILY_METRICS_QUERY = """
WITH deduplicated AS (
    SELECT DISTINCT ON (message.id)
        timestamp,
        message.usage.input_tokens as input_tokens,
        message.usage.output_tokens as output_tokens,
        message.usage.cache_creation_input_tokens as cache_creation,
        message.usage.cache_read_input_tokens as cache_read
    FROM read_json_auto('{path}',
        maximum_object_size=104857600,
        ignore_errors=true
    )
    WHERE type = 'assistant'
      AND message.usage IS NOT NULL
      AND message.id IS NOT NULL
      AND timestamp >= '{start_date}'
      AND timestamp <= '{end_date}'
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
