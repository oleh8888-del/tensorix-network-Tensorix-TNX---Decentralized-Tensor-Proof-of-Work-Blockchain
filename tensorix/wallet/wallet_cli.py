"""
Tensorix Network (TNX) - Command Line Wallet
Generates Ed25519 addresses, manages keys, checks balances, and signs/transfers TNX.
"""

import os
import sys
import json
import argparse
import httpx
from decimal import Decimal, InvalidOperation, localcontext

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ..blockchain.transaction import Transaction, COIN, MIN_TX_FEE, valid_address
from ..consensus.crypto import generate_keypair, pub_to_address

DEFAULT_WALLET_FILE = "tensorix_wallet.json"
DEFAULT_NODE_URL = "http://127.0.0.1:8333"


def tnx_to_units(value, *, name: str) -> int:
    """Parse a positive TNX amount without rounding or binary float truncation."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive TNX amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{name} must be a finite positive TNX amount")
    with localcontext() as context:
        context.prec = max(28, len(amount.as_tuple().digits) + 8)
        units = amount * COIN
    if units != units.to_integral_value():
        raise ValueError(f"{name} supports at most 8 decimal places")
    return int(units)


def create_wallet(filepath: str = DEFAULT_WALLET_FILE):
    """Create and save a new secure Ed25519 wallet."""
    if os.path.exists(filepath):
        print(f"⚠️ Wallet file '{filepath}' already exists! Aborting to avoid overwrite.")
        return
    
    priv_hex, pub_hex, address = generate_keypair()
    wallet_data = {
        "address": address,
        "public_key": pub_hex,
        "private_key": priv_hex,
        "network": "Tensorix Mainnet"
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(wallet_data, f, indent=2)
        
    print("=" * 60)
    print("✨ NEW TENSORIX WALLET CREATED SUCCESSFULLY!")
    print(f"File Saved:  {filepath}")
    print(f"TNX Address: {address}")
    print(f"Public Key:  {pub_hex}")
    print("=" * 60)
    print("🔒 KEEP YOUR PRIVATE KEY SAFE. NEVER SHARE IT.")


def load_wallet(filepath: str = DEFAULT_WALLET_FILE) -> dict:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Wallet file '{filepath}' not found. Run 'create' first.")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def check_balance(node_url: str = DEFAULT_NODE_URL, filepath: str = DEFAULT_WALLET_FILE):
    wallet = load_wallet(filepath)
    addr = wallet["address"]
    url = f"{node_url.rstrip('/')}/balance/{addr}"
    
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.get(url)
            if res.status_code == 200:
                data = res.json()
                print("=" * 50)
                print(f"📬 TENSORIX WALLET BALANCE")
                print(f"Address:      {addr}")
                print(f"Balance:      {data['balance_tnx']:.6f} TNX ({data['balance_atomic']} units)")
                print(f"Tx Nonce:     {data['nonce']}")
                print("=" * 50)
            else:
                print(f"Error from node: {res.text}")
    except Exception as e:
        print(f"Failed to connect to Tensorix Node at {node_url}: {e}")


def send_tnx(
    recipient: str,
    amount_tnx: str | float,
    fee_tnx: str | float = "10",
    node_url: str = DEFAULT_NODE_URL,
    filepath: str = DEFAULT_WALLET_FILE
):
    try:
        amount_units = tnx_to_units(amount_tnx, name="Amount")
        fee_units = tnx_to_units(fee_tnx, name="Fee")
        if fee_units < MIN_TX_FEE:
            raise ValueError("Wallet-to-wallet transfers require a fee of at least 10 TNX")
        if not valid_address(recipient):
            raise ValueError("A complete TNX recipient address is required")
    except ValueError as exc:
        print(f"❌ Error: {exc}")
        return

    wallet = load_wallet(filepath)
    sender = wallet["address"]

    # 1. Fetch current sender nonce and balance from node
    balance_url = f"{node_url.rstrip('/')}/balance/{sender}"
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.get(balance_url)
            if res.status_code != 200:
                print(f"Node error: {res.text}")
                return
            bdata = res.json()
            current_nonce = bdata["nonce"]
            current_balance = bdata["balance_atomic"]
    except Exception as e:
        print(f"Could not connect to node: {e}")
        return

    total_required = amount_units + fee_units
    if current_balance < total_required:
        print(f"❌ Insufficient balance: Available {current_balance / COIN:.6f} TNX, Required {total_required / COIN:.6f} TNX.")
        return

    # 2. Build and sign transaction
    tx = Transaction(
        sender=sender,
        recipient=recipient,
        amount=amount_units,
        fee=fee_units,
        nonce=current_nonce,
        public_key=wallet["public_key"]
    )
    tx.sign(wallet["private_key"])

    # 3. Broadcast to node
    send_url = f"{node_url.rstrip('/')}/tx/send"
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.post(send_url, json={
                "sender": tx.sender,
                "recipient": tx.recipient,
                "amount": tx.amount,
                "fee": tx.fee,
                "nonce": tx.nonce,
                "public_key": tx.public_key,
                "signature": tx.signature
            })
            if res.status_code == 200:
                print("=" * 60)
                print(f"🚀 TRANSACTION BROADCASTED SUCCESSFULLY!")
                print(f"TxID:        {tx.txid}")
                print(f"Amount:      {Decimal(amount_units) / COIN:.8f} TNX -> {recipient}")
                print(f"Fee:         {Decimal(fee_units) / COIN:.8f} TNX")
                print("=" * 60)
            else:
                print(f"❌ Transaction rejected by node: {res.text}")
    except Exception as e:
        print(f"Failed to broadcast transaction: {e}")


def main():
    parser = argparse.ArgumentParser(description="Tensorix (TNX) Wallet CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # create
    sub_create = subparsers.add_parser("create", help="Create a new wallet")
    sub_create.add_argument("--file", default=DEFAULT_WALLET_FILE, help="Wallet file path")

    # balance
    sub_bal = subparsers.add_parser("balance", help="Check wallet balance")
    sub_bal.add_argument("--node", default=DEFAULT_NODE_URL, help="Node URL")
    sub_bal.add_argument("--file", default=DEFAULT_WALLET_FILE, help="Wallet file path")

    # address
    sub_addr = subparsers.add_parser("address", help="Show wallet address")
    sub_addr.add_argument("--file", default=DEFAULT_WALLET_FILE, help="Wallet file path")

    # send
    sub_send = subparsers.add_parser("send", help="Send TNX coins")
    sub_send.add_argument("--to", required=True, help="Recipient TNX address")
    sub_send.add_argument("--amount", required=True, help="Amount in TNX (up to 8 decimal places)")
    sub_send.add_argument("--fee", default="10", help="Wallet transfer fee in TNX (default/minimum 10 TNX -> Founder Wallet)")
    sub_send.add_argument("--node", default=DEFAULT_NODE_URL, help="Node URL")
    sub_send.add_argument("--file", default=DEFAULT_WALLET_FILE, help="Wallet file path")

    args = parser.parse_args()

    if args.command == "create":
        create_wallet(args.file)
    elif args.command == "balance":
        check_balance(args.node, args.file)
    elif args.command == "address":
        wallet = load_wallet(args.file)
        print(f"TNX Address: {wallet['address']}")
    elif args.command == "send":
        send_tnx(args.to, args.amount, args.fee, args.node, args.file)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

