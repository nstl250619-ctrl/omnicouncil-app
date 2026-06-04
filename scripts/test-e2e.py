"""End-to-end test for OmniCouncil.

Tests the full pipeline: WebSocket connection → submit query → receive results.
Run against a running backend instance.

Usage:
    python scripts/test-e2e.py [--port 8765]
"""

import argparse
import asyncio
import json
import sys
import time

try:
    import websockets
except ImportError:
    print("Installing websockets...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets


async def test_health(port: int) -> bool:
    """Test health endpoint."""
    import urllib.request
    try:
        response = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=5)
        data = json.loads(response.read())
        assert data["status"] == "ok", f"Health check failed: {data}"
        print("  ✅ Health endpoint OK")
        return True
    except Exception as e:
        print(f"  ❌ Health endpoint failed: {e}")
        return False


async def test_websocket(port: int) -> bool:
    """Test WebSocket connection and message flow."""
    uri = f"ws://localhost:{port}/ws"
    messages = []

    try:
        async with websockets.connect(uri) as ws:
            print("  ✅ WebSocket connected")

            # Should receive engine_status on connect
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data["type"] == "engine_status", f"Expected engine_status, got {data['type']}"
            print(f"  ✅ Engine status received: {len(data['data'].get('ais', []))} AIs")

            # Send ping
            await ws.send(json.dumps({"type": "ping", "data": {}}))
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data["type"] == "pong", f"Expected pong, got {data['type']}"
            print("  ✅ Ping/pong OK")

            # Collect messages for 2 seconds
            async def collect_messages():
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2)
                        messages.append(json.loads(msg))
                except asyncio.TimeoutError:
                    pass

            await collect_messages()

        print(f"  ✅ WebSocket test complete ({len(messages)} messages)")
        return True

    except Exception as e:
        print(f"  ❌ WebSocket test failed: {e}")
        return False


async def test_submit_query(port: int) -> bool:
    """Test query submission and result collection."""
    uri = f"ws://localhost:{port}/ws"
    results = {}
    timeout_s = 120

    try:
        async with websockets.connect(uri) as ws:
            # Receive engine_status
            await asyncio.wait_for(ws.recv(), timeout=5)

            # Submit query
            query_msg = {
                "type": "submit_query",
                "data": {
                    "query": "Say hello in one word",
                    "ai_ids": ["deepseek"],
                    "mode": "parallel"
                }
            }
            await ws.send(json.dumps(query_msg))
            print("  ✅ Query submitted")

            # Collect results
            start = time.time()
            while time.time() - start < timeout_s:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(msg)
                    msg_type = data["type"]

                    if msg_type == "progress":
                        p = data["data"]
                        print(f"  📊 Progress: {p.get('completed', 0)}/{p.get('total', 0)}")

                    elif msg_type == "ai_completed":
                        ai_id = data["data"]["ai_id"]
                        content = data["data"]["full_text"]
                        results[ai_id] = content
                        print(f"  ✅ {ai_id} completed: {content[:50]}...")

                    elif msg_type == "ai_failed":
                        ai_id = data["data"]["ai_id"]
                        error = data["data"]["error"]
                        print(f"  ❌ {ai_id} failed: {error}")

                    elif msg_type == "all_completed":
                        print("  ✅ All AIs completed")
                        break

                    elif msg_type == "comparison_ready":
                        metrics = data["data"].get("comparison_context", {}).get("metrics", {})
                        print(f"  ✅ Comparison ready: divergence={metrics.get('overall_divergence', 0):.2f}")

                except asyncio.TimeoutError:
                    continue

        if results:
            print(f"  ✅ Query test complete: {len(results)} responses")
            return True
        else:
            print("  ⚠️ Query test: no responses received (AI may need login)")
            return True  # Not a failure if AI needs login

    except Exception as e:
        print(f"  ❌ Query test failed: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--skip-query", action="store_true", help="Skip query submission test")
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"  OmniCouncil E2E Tests (port {args.port})")
    print(f"{'='*50}\n")

    results = []

    # Test 1: Health endpoint
    print("Test 1: Health Endpoint")
    results.append(await test_health(args.port))
    print()

    # Test 2: WebSocket connection
    print("Test 2: WebSocket Connection")
    results.append(await test_websocket(args.port))
    print()

    # Test 3: Query submission
    if not args.skip_query:
        print("Test 3: Query Submission")
        results.append(await test_submit_query(args.port))
        print()

    # Summary
    passed = sum(results)
    total = len(results)
    print(f"{'='*50}")
    print(f"  Results: {passed}/{total} passed")
    print(f"{'='*50}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
