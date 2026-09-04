with open('scripts/common.py', 'r') as f:
    content = f.read()

# We need to add the cleanup logic at the start of is_subagent
cleanup_logic = """    cache_dir = get_cache_dir()
    try:
        now_time = time.time()
        for fname in os.listdir(cache_dir):
            if fname.startswith("agy_issued_token_"):
                fpath = os.path.join(cache_dir, fname)
                if now_time - os.path.getmtime(fpath) > 86400:
                    os.remove(fpath)
    except Exception:
        pass

    transcript_path = data.get("transcriptPath", "")"""

content = content.replace('    transcript_path = data.get("transcriptPath", "")', cleanup_logic)

with open('scripts/common.py', 'w') as f:
    f.write(content)
