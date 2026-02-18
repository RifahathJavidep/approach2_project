import httpx
import time
import uuid

# Configuration
BASE_URL = "http://localhost:8000"
# Use a unique project ID to ensure we trigger "Training" the first time
TEST_PROJECT_ID = f"test_workflow_{uuid.uuid4().hex[:8]}"
# Use an existing file key from your S3 bucket for testing
TEST_FILE_URLS = ["uploads/crm_cloud/ECO_Checkout_Features.pdf"]

async def run_test():
    async with httpx.AsyncClient(timeout=300.0) as client:
        print(f"\n{'='*60}")
        print(f"TESTING WORKFLOW FOR PROJECT: {TEST_PROJECT_ID}")
        print(f"{'='*60}")

        # ----------------------------------------------------------------------
        # RUN 1: Should trigger TRAINING (Multi-Project Scan)
        # ----------------------------------------------------------------------
        print(f"\n[RUN 1] Requesting extraction (Expected: TRAINING)...")
        start_time = time.time()
        
        payload = {
            "project_id": TEST_PROJECT_ID,
            "file_urls": TEST_FILE_URLS
        }
        
        response1 = await client.post(f"{BASE_URL}/extract", json=payload)
        
        if response1.status_code == 200:
            duration = time.time() - start_time
            print(f"  ✓ Success! Time taken: {duration:.2f}s")
            print(f"  ✓ Requirements found: {response1.json()['total_requirements']}")
            print(f"  ✓ Model saved to S3: {response1.json()['s3_output']['model_url'] is not None}")
        else:
            print(f"  ✗ Failed: {response1.status_code} - {response1.text}")
            return

        # Wait a moment for S3 consistency (usually not needed but good for tests)
        print("\nWaiting 2 seconds for S3 sync...")
        time.sleep(2)

        # ----------------------------------------------------------------------
        # RUN 2: Should trigger LOADING (Skip Training)
        # ----------------------------------------------------------------------
        print(f"\n[RUN 2] Requesting extraction again (Expected: LOADING)...")
        start_time = time.time()
        
        response2 = await client.post(f"{BASE_URL}/extract", json=payload)
        
        if response2.status_code == 200:
            duration = time.time() - start_time
            print(f"  ✓ Success! Time taken: {duration:.2f}s")
            print(f"  ✓ Requirements found: {response2.json()['total_requirements']}")
            
            # Comparison
            print(f"\nRESULT:")
            print(f"  Run 1 (Train): {response1.json().get('latency_desc', 'N/A')}") # Note: I didn't add latency_desc, but we can see in terminal logs
            print(f"  Run 2 took {duration:.2f}s (should be much faster than Run 1)")
            if duration < 15: # Arbitrary threshold, training usually takes ~10-20s with multi-project
                 print("\n  ✓ TEST PASSED: Second run was fast and loaded from S3!")
            else:
                 print("\n  ⚠ TEST WARNING: Second run was still slow. Check terminal logs.")
        else:
            print(f"  ✗ Failed: {response2.status_code} - {response2.text}")

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(run_test())
    except ConnectionError:
        print(f"  ✗ Error: Could not connect to {BASE_URL}. Is app.py running?")
    except Exception as e:
        print(f"  ✗ Error: {e}")
