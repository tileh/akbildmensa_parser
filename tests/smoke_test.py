import sys

from main import Parser


def main():
    parser = Parser()
    try:
        feed = parser.generate_feed()
    except Exception as e:
        print("SMOKE FAILED: parser exception ->", e)
        sys.exit(2)

    if "<day" not in feed or "<meal>" not in feed:
        print("SMOKE FAILED: feed missing <day> or <meal>")
        sys.exit(2)

    print("SMOKE OK")


if __name__ == "__main__":
    main()
