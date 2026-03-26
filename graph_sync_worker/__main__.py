"""Entry point: python -m graph_sync_worker"""

from graph_sync_worker.consumer import GraphSyncConsumer

if __name__ == "__main__":
    GraphSyncConsumer().start()
