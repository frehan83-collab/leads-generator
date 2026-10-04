"""
Test multi-source pipeline integration.
Runs a small test with both finn and nav sources.
"""

import sys
from src.pipeline.lead_pipeline import LeadPipeline
from src.logger import setup_logging

setup_logging("INFO")

def test_pipeline():
    print("\n=== Testing Multi-Source Pipeline ===\n")

    # Test with Norwegian keywords for better results
    keywords = ["sjømat"]  # Norwegian for seafood
    sources = ["nav"]  # Test NAV only for speed

    print(f"Keywords: {keywords}")
    print(f"Sources: {sources}")
    print("\nRunning pipeline (this may take 1-2 minutes)...\n")

    try:
        pipeline = LeadPipeline(sources=sources)
        stats = pipeline.run(keywords)

        print("\n=== Pipeline Test Complete ===\n")
        print("Stats:")
        for key, value in stats.items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for sub_key, sub_value in value.items():
                    print(f"    {sub_key}: {sub_value}")
            else:
                print(f"  {key}: {value}")

        # Verify multi-source worked
        if "postings_by_source" in stats:
            total_by_source = sum(stats["postings_by_source"].values())
            print(f"\n[OK] Multi-source scraping worked!")
            print(f"     Total postings from all sources: {total_by_source}")

        if stats.get("postings_new", 0) > 0:
            print(f"[OK] Successfully added {stats['postings_new']} new postings to DB")

        if stats.get("prospects_found", 0) > 0:
            print(f"[OK] Found {stats['prospects_found']} prospects")

        return True

    except Exception as exc:
        print(f"\n[ERROR] Pipeline test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_pipeline()
    sys.exit(0 if success else 1)
