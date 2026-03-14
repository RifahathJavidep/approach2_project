import os
import ssl
import redis
from dotenv import load_dotenv

load_dotenv()

def test_redis_connection():
    url = os.getenv('CELERY_BROKER_URL')
    print(f"Testing connection to: {url}")
    
    try:
        # For AWS ElastiCache with Encryption in Transit, we need SSL
        if url.startswith('rediss://'):
            r = redis.from_url(
                url, 
                ssl_cert_reqs=None # Same as ssl.CERT_NONE for testing
            )
        else:
            r = redis.from_url(url)
            
        response = r.ping()
        if response:
            print("✅ Success! Connected to AWS ElastiCache.")
        else:
            print("❌ Ping failed.")
            
    except Exception as e:
        print(f"❌ Connection FAILED: {e}")
        print("\nPossible reasons:")
        print("1. Security Group: Is Port 6379 open for your IP?")
        print("2. SSL: Does the cluster require SSL (Encryption in Transit)?")
        print("3. Network: Is the cluster in the same VPC or accessible over the internet?")

if __name__ == "__main__":
    test_redis_connection()
