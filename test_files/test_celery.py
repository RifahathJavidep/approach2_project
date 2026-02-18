import httpx
import time
import asyncio
import uuid

# Configuration
BASE_URL = "http://localhost:8000"
# Use a unique project ID to trigger training
TEST_PROJECT_ID = f"celery_test_{uuid.uuid4().hex[:8]}"
# Use a verified S3 key from your bucket
TEST_FILE_URLS = ["uploads/crm_cloud/ECO_Checkout_Features.pdf"]

async def run_celery_test():
    async with httpx.AsyncClient(timeout=300.0) as client:
        print(f"\n{'='*60}")
        print(f"TESTING ASYNC CELERY WORKFLOW")
        print(f"PROJECT: {TEST_PROJECT_ID}")
        print(f"{'='*60}")

        # ----------------------------------------------------------------------
        # 1. SUBMIT ASYNC TASK
        # ----------------------------------------------------------------------
        print(f"\n1. Submitting extraction task to /extract-async...")
        payload = {
            "project_id": TEST_PROJECT_ID,
            "file_urls": TEST_FILE_URLS
        }
        
        try:
            response = await client.post(f"{BASE_URL}/extract-async", json=payload)
            if response.status_code != 200:
                print(f"  ✗ Failed to submit task: {response.status_code} - {response.text}")
                return
            
            resp_data = response.json()
            task_id = resp_data.get("task_id")
            print(f"  ✓ Task accepted! Task ID: {task_id}")
            
        except Exception as e:
            print(f"  ✗ Error connecting to API: {e}")
            return

        # ----------------------------------------------------------------------
        # 2. POLL FOR STATUS
        # ----------------------------------------------------------------------
        print(f"\n2. Polling status for Task ID: {task_id}...")
        
        start_time = time.time()
        while True:
            try:
                status_resp = await client.get(f"{BASE_URL}/status/{task_id}")
                if status_resp.status_code != 200:
                    print(f"  ✗ Status check failed: {status_resp.status_code}")
                    break
                
                status_data = status_resp.json()
                current_status = status_data.get("status")
                elapsed = time.time() - start_time
                
                print(f"  [{elapsed:4.1f}s] Status: {current_status}")
                
                if current_status == "SUCCESS":
                    print(f"\n{'='*60}")
                    print(f"  ✓ SUCCESS! Background task complete.")
                    print(f"  ✓ Result Summary: {status_data.get('result', {})}")
                    print(f"{'='*60}")
                    break
                elif current_status == "FAILURE":
                    print(f"\n{'='*60}")
                    print(f"  ✗ TASK FAILED!")
                    print(f"  Error: {status_data.get('error')}")
                    print(f"{'='*60}")
                    break
                
                # Wait before next poll
                await asyncio.sleep(5)
                
                if elapsed > 600: # 10 minute timeout
                    print("  ✗ Test timed out after 10 minutes.")
                    break
                    
            except Exception as e:
                print(f"  ✗ Error during polling: {e}")
                break

if __name__ == "__main__":
    try:
        asyncio.run(run_celery_test())
    except KeyboardInterrupt:
        print("\nTest cancelled by user.")
