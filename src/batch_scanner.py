import time

def batched(items, batch_size=3):
    """
    Yield successive batches from a list.
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def process_batches(symbols, process_symbol, batch_size=3, delay=5):
    """
    Process symbols in batches with a delay between batches.

    symbols: list of (symbol, (exchange, token))
    process_symbol: callback(symbol, exchange, token)
    """
    symbol_list = list(symbols.items())

    for batch_no, batch in enumerate(batched(symbol_list, batch_size), start=1):
        print(f"\n===== Batch {batch_no} =====")

        for symbol, (exchange, token) in batch:
            process_symbol(symbol, exchange, token)

        if batch_no * batch_size < len(symbol_list):
            print(f"Waiting {delay} seconds before next batch...")
            time.sleep(delay)
