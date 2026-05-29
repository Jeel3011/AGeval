"""
ageval/cli.py

AGeval CLI.
Provides onboarding `ageval setup` and testing `ageval test`.
"""
import argparse
import sys
import time

def setup():
    print("Welcome to AGeval Onboarding!")
    print("-----------------------------")
    api_key = input("1. Enter your AGeval API Key (or press Enter to skip): ").strip()
    if api_key:
        with open(".env", "a") as f:
            f.write(f"\nAGEVAL_API_KEY={api_key}\n")
        print("✅ Added AGEVAL_API_KEY to .env")
    else:
        print("⚠️ Skipped setting API key.")

    print("\n🎉 Setup complete! You're ready to evaluate your agents.")

def test(agent, dataset):
    print(f"Running AGeval CI/CD test runner for agent '{agent}' against dataset '{dataset}'...")
    print("Loading test cases from golden datasets hub...")
    time.sleep(1)
    print(f"Found 5 test cases in '{dataset}'. Starting evaluation...")

    # Mocking test execution for Phase 2 demo
    import random
    pass_count = 0
    fail_count = 0

    for i in range(1, 6):
        time.sleep(0.5)
        score = random.uniform(0.6, 1.0)
        status = "✅ PASS" if score >= 0.8 else "❌ FAIL"
        if score >= 0.8:
            pass_count += 1
        else:
            fail_count += 1
        print(f"  Test Case #{i}: Faithfulness: {score:.2f} | {status}")

    print("\n-----------------------------")
    print(f"Test Run Complete: {pass_count} Passed, {fail_count} Failed.")
    if fail_count > 0:
        print("Pipeline assertion failed. Score dropped below threshold.")
        sys.exit(1)
    else:
        print("All metrics passed thresholds. Ready for deployment!")
        sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="AGeval CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup", help="Run onboarding setup")

    test_parser = subparsers.add_parser("test", help="Run automated evaluations")
    test_parser.add_argument("--agent", required=True, help="Agent ID or entrypoint to test")
    test_parser.add_argument("--dataset", required=True, help="Golden dataset name to run against")

    args = parser.parse_args()

    if args.command == "setup":
        setup()
    elif args.command == "test":
        test(args.agent, args.dataset)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
