"""
Patch Hindsight's openai_compatible_llm.py to handle Groq's separate token and request rate limit headers.
"""
path = '/app/api/hindsight_api/engine/providers/openai_compatible_llm.py'
with open(path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update reset_seconds logic to prefer token reset when token limit is hit
old_block = '''        reset_seconds: list[float] = []
        body_text_lower = _status_error_body_text(e).lower()
        is_token_limit = "token" in body_text_lower or "tpm" in body_text_lower
        is_req_limit = "request" in body_text_lower or "rpm" in body_text_lower
        if is_token_limit and not is_req_limit and "x-ratelimit-reset-tokens" in headers:
            token_sec = _parse_go_duration_seconds(headers["x-ratelimit-reset-tokens"])
            if token_sec is not None and token_sec > 0:
                reset_seconds.append(token_sec)
        else:
            for key in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
                if key in headers:
                    seconds = _parse_go_duration_seconds(headers[key])
                    if seconds is not None and seconds > 0:
                        reset_seconds.append(seconds)
        if reset_seconds:
            retry_candidates.append(now + timedelta(seconds=max(reset_seconds)))'''

new_block = '''        reset_seconds: list[float] = []
        body_text_lower = _status_error_body_text(e).lower()
        is_token_limit = "tokens per minute" in body_text_lower or "tpm" in body_text_lower or ("token" in body_text_lower and "rate limit" in body_text_lower)
        is_req_limit = "requests per minute" in body_text_lower or "rpm" in body_text_lower
        if is_token_limit and not is_req_limit and "x-ratelimit-reset-tokens" in headers:
            token_sec = _parse_go_duration_seconds(headers["x-ratelimit-reset-tokens"])
            if token_sec is not None and token_sec > 0:
                reset_seconds.append(token_sec)
        else:
            for key in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
                if key in headers:
                    seconds = _parse_go_duration_seconds(headers[key])
                    if seconds is not None and seconds > 0:
                        reset_seconds.append(seconds)
        if reset_seconds:
            retry_candidates.append(now + timedelta(seconds=max(reset_seconds)))'''

assert old_block in code, 'old_block not found'
code = code.replace(old_block, new_block, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print('Successfully updated patch in openai_compatible_llm.py')
