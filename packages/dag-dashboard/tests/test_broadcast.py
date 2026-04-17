"""Tests for broadcast hub."""
import asyncio
import pytest
from dag_dashboard.broadcast import Broadcaster


@pytest.mark.asyncio
async def test_subscribe_returns_async_iterator():
    """Test that subscribe returns an async context manager yielding a queue."""
    broadcaster = Broadcaster()
    
    async with broadcaster.subscribe("run_123") as queue:
        assert isinstance(queue, asyncio.Queue)


@pytest.mark.asyncio
async def test_publish_sends_to_all_subscribers():
    """Test that publish sends events to all subscribers for a run_id."""
    broadcaster = Broadcaster()
    received_1 = []
    received_2 = []
    
    async def subscriber_1():
        async with broadcaster.subscribe("run_123") as queue:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            received_1.append(event)
    
    async def subscriber_2():
        async with broadcaster.subscribe("run_123") as queue:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            received_2.append(event)
    
    # Start subscribers
    sub1_task = asyncio.create_task(subscriber_1())
    sub2_task = asyncio.create_task(subscriber_2())
    
    # Give subscribers time to register
    await asyncio.sleep(0.01)
    
    # Publish event
    test_event = {"type": "test", "data": "hello"}
    await broadcaster.publish("run_123", test_event)
    
    # Wait for subscribers to receive
    await asyncio.wait_for(asyncio.gather(sub1_task, sub2_task), timeout=1.0)
    
    assert received_1 == [test_event]
    assert received_2 == [test_event]


@pytest.mark.asyncio
async def test_publish_isolates_run_ids():
    """Test that events are only sent to subscribers of the matching run_id."""
    broadcaster = Broadcaster()
    received_123 = []
    received_456 = []
    
    async def subscriber_123():
        async with broadcaster.subscribe("run_123") as queue:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.2)
                received_123.append(event)
            except asyncio.TimeoutError:
                pass
    
    async def subscriber_456():
        async with broadcaster.subscribe("run_456") as queue:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            received_456.append(event)
    
    sub123_task = asyncio.create_task(subscriber_123())
    sub456_task = asyncio.create_task(subscriber_456())
    
    await asyncio.sleep(0.01)
    
    # Publish only to run_456
    test_event = {"type": "test", "data": "hello"}
    await broadcaster.publish("run_456", test_event)
    
    await asyncio.wait_for(asyncio.gather(sub123_task, sub456_task), timeout=1.0)
    
    assert received_123 == []  # run_123 subscriber should not receive event
    assert received_456 == [test_event]


@pytest.mark.asyncio
async def test_unsubscribe_on_context_exit():
    """Test that exiting the context manager unsubscribes."""
    broadcaster = Broadcaster()
    
    # Subscribe and immediately exit
    async with broadcaster.subscribe("run_123") as queue:
        pass
    
    # Verify subscriber was cleaned up
    assert "run_123" not in broadcaster._subscribers or len(broadcaster._subscribers["run_123"]) == 0
    
    # Publish event - should not raise error or block
    await broadcaster.publish("run_123", {"type": "test"})


@pytest.mark.asyncio
async def test_multiple_events_to_same_subscriber():
    """Test that a subscriber can receive multiple events."""
    broadcaster = Broadcaster()
    received = []
    
    async def subscriber():
        async with broadcaster.subscribe("run_123") as queue:
            for _ in range(3):
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                received.append(event)
    
    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0.01)
    
    # Publish three events
    for i in range(3):
        await broadcaster.publish("run_123", {"index": i})
    
    await asyncio.wait_for(sub_task, timeout=1.0)
    
    assert received == [{"index": 0}, {"index": 1}, {"index": 2}]
