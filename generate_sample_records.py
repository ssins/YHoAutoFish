from core.record_manager import RecordManager


def main():
    manager = RecordManager()
    sample = manager.generate_sample_records()

    import json

    with open("sample_records.json", "w", encoding="utf-8") as file:
        json.dump(sample, file, ensure_ascii=False, indent=4)

    with open("records.json", "w", encoding="utf-8") as file:
        json.dump(sample, file, ensure_ascii=False, indent=4)

    print("sample records generated")


if __name__ == "__main__":
    main()
