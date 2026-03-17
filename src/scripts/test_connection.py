from src.exchange.binance_client import create_binance_client

def main():
    client = create_binance_client()
    try:
        # Test connection by fetching account information
        account_info = client.get_account()
        print("Connection successful. Account information:")
        print(account_info)
    except Exception as e:
        print("Connection failed:", e)

if __name__ == "__main__":
    main()