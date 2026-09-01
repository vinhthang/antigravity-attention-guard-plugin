#!/usr/bin/env python3
import sys, json, os

OUTPUT_SIZE_THRESHOLD = 20000  # bytes


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({}))
        return

    transcript_path = payload.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        print(json.dumps({}))
        return

    # Read the last few lines of the transcript to find recent tool outputs
    large_outputs = []
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            remainder = b""
            lines_checked = 0
            max_lines_to_check = 10  # Only check the last 10 transcript entries

            while pos > 0 and lines_checked < max_lines_to_check:
                read_size = min(65536, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                data = chunk + remainder
                split_lines = data.split(b"\n")
                remainder = split_lines[0]

                for line in reversed(split_lines[1:]):
                    if not line.strip():
                        continue
                    lines_checked += 1
                    if lines_checked > max_lines_to_check:
                        break
                    try:
                        record = json.loads(line.decode("utf-8"))
                        # Check GENERIC steps (tool outputs) for large content
                        if record.get("type") == "GENERIC" and record.get("source") == "MODEL":
                            content = record.get("content", "")
                            content_size = len(content.encode("utf-8")) if content else 0
                            if content_size > OUTPUT_SIZE_THRESHOLD:
                                large_outputs.append(content_size)
                    except Exception:
                        continue

            if remainder.strip() and lines_checked < max_lines_to_check:
                try:
                    record = json.loads(remainder.decode("utf-8"))
                    if record.get("type") == "GENERIC" and record.get("source") == "MODEL":
                        content = record.get("content", "")
                        content_size = len(content.encode("utf-8")) if content else 0
                        if content_size > OUTPUT_SIZE_THRESHOLD:
                            large_outputs.append(content_size)
                except Exception:
                    pass
    except Exception:
        print(json.dumps({}))
        return

    if large_outputs:
        max_size = max(large_outputs)
        size_kb = max_size // 1024
        warning = (
            f"OUTPUT SIZE WARNING: A recent tool output was {size_kb}KB "
            f"(threshold: {OUTPUT_SIZE_THRESHOLD // 1024}KB). "
            "Large outputs consume context window space and cause attention dilution. "
            "Use `rtk` prefix or pipe to `rtk log` / `rtk json` to compress output."
        )
        print(json.dumps({"injectSteps": [{"ephemeralMessage": warning}]}))
    else:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
