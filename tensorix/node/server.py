"""
Tensorix Network (TNX) - Node RPC Daemon & REST API
Provides full REST/RPC endpoints for miners, wallets, and P2P peer nodes.
"""

import os
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
from ..blockchain.chain import Blockchain, COIN, MIN_TX_FEE, POOL_FEE_PCT, FOUNDER_ADDRESS
from ..blockchain.block import Block
from ..blockchain.transaction import Transaction, valid_address
from ..consensus.crypto import pub_to_address

app = FastAPI(title="Tensorix Node RPC & Explorer", version="1.0.0")
blockchain: Optional[Blockchain] = None
peers: set = set()


class SendTxRequest(BaseModel):
    sender: str
    recipient: str
    amount: int
    fee: int = 1_000_000_000  # Default 10 TNX
    nonce: int
    public_key: str
    signature: str


class BlockSubmitRequest(BaseModel):
    index: int
    prev_hash: str
    timestamp: int
    difficulty: float
    nonce: int
    merkle_root: str
    transactions: List[dict]


@app.on_event("startup")
def startup_event():
    global blockchain
    data_dir = os.environ.get("TENSORIX_DATA_DIR", "tensorix_data")
    blockchain = Blockchain(data_dir=data_dir)


@app.get("/", response_class=HTMLResponse)
def root_dashboard():
    height = blockchain.get_latest_block().index if blockchain.chain else 0
    diff = blockchain.get_latest_block().difficulty if blockchain.chain else 1.0
    latest_hash = blockchain.get_latest_block().hash if blockchain.chain else "None"
    supply = (sum(tx.amount for b in blockchain.chain for tx in b.transactions if tx.is_coinbase()) / COIN) if blockchain.chain else 0.0

    recent_blocks = list(reversed(blockchain.chain[-10:])) if blockchain.chain else []
    rows_html = ""
    for b in recent_blocks:
        rows_html += f"""
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; color: #58a6ff; font-weight: bold;">#{b.index}</td>
            <td style="padding: 12px; font-family: monospace; color: #7ee787;">{b.hash[:20]}...</td>
            <td style="padding: 12px; color: #c9d1d9;">{b.difficulty:.2f}</td>
            <td style="padding: 12px; color: #d2a8ff;">{b.nonce}</td>
            <td style="padding: 12px; color: #8b949e;">{len(b.transactions)} txs</td>
            <td style="padding: 12px; color: #f0883e;">{b.transactions[0].amount / COIN:.2f} TNX</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="UTF-8">
        <title>Tensorix (TNX) - Live Network Explorer</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body {{ background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 24px; }}
            .container {{ max-width: 1100px; margin: 0 auto; }}
            .header {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #30363d; padding-bottom: 16px; margin-bottom: 24px; }}
            .logo {{ font-size: 26px; font-weight: bold; color: #58a6ff; letter-spacing: 1px; }}
            .status-badge {{ background: #238636; color: white; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 30px; }}
            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px; }}
            .card-title {{ color: #8b949e; font-size: 12px; text-transform: uppercase; font-weight: bold; margin-bottom: 6px; }}
            .card-value {{ font-size: 24px; font-weight: bold; color: #f0f6fc; }}
            .card-sub {{ font-size: 11px; color: #7ee787; margin-top: 4px; }}
            .table-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; overflow-x: auto; }}
            .code-box {{ background: #0b0e14; border: 1px solid #21262d; padding: 12px 16px; border-radius: 6px; font-family: monospace; color: #79c0ff; font-size: 13px; margin-top: 8px; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
            th {{ padding: 10px 12px; color: #8b949e; border-bottom: 1px solid #30363d; font-size: 12px; text-transform: uppercase; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">⚡ TENSORIX NETWORK (TNX)</div>
                <div class="status-badge">● EXPERIMENTAL REFERENCE</div>
            </div>

            <div class="grid">
                <div class="card">
                    <div class="card-title">Висота Блокчейну</div>
                    <div class="card-value">#{height}</div>
                    <div class="card-sub">Оновлення кожні 5 сек</div>
                </div>
                <div class="card">
                    <div class="card-title">Складність LWMA</div>
                    <div class="card-value">{diff:.2f}</div>
                    <div class="card-sub">Tensor-PoW (INT8 GEMM)</div>
                </div>
                <div class="card">
                    <div class="card-title">Здобуто Монет</div>
                    <div class="card-value">{supply:.2f} TNX</div>
                    <div class="card-sub">Формула емісії ще потребує узгодження з лімітом 21 млн</div>
                </div>
                <div class="card">
                    <div class="card-title">Цільовий Час Блоку</div>
                    <div class="card-value">60 сек</div>
                    <div class="card-sub">Халвінг кожні 2 роки</div>
                </div>
            </div>

            <div class="grid" style="margin-bottom: 24px;">
                <div class="card" style="border-left: 4px solid #f0883e;">
                    <div class="card-title">Комісія за Транзакцію (Tx Fee)</div>
                    <div class="card-value" style="color: #f0883e;">10 TNX</div>
                    <div class="card-sub">100% надходить засновнику</div>
                </div>
                <div class="card" style="border-left: 4px solid #58a6ff;">
                    <div class="card-title">Комісія Stratum-Пулу</div>
                    <div class="card-value" style="color: #58a6ff;">2%</div>
                    <div class="card-sub">98% майнеру / 2% засновнику</div>
                </div>
                <div class="card" style="border-left: 4px solid #a371f7;">
                    <div class="card-title">Комісія Майнера (Dev Fee)</div>
                    <div class="card-value" style="color: #a371f7;">2%</div>
                    <div class="card-sub">Неперевірений legacy scheduler; не гарантує 2% роботи</div>
                </div>
                <div class="card" style="border-left: 4px solid #7ee787;">
                    <div class="card-title">Гаманець Засновника</div>
                    <div class="card-value" style="font-size: 13px; font-family: monospace; word-break: break-all; color: #7ee787;">{FOUNDER_ADDRESS}</div>
                    <div class="card-sub">Отримувач усіх комісій мережі</div>
                </div>
            </div>

            <div class="card" style="margin-bottom: 24px;">
                <div class="card-title">🔌 ПАРАМЕТРИ ПІДКЛЮЧЕННЯ ДЛЯ МАЙНЕРІВ</div>
                <div style="font-size: 13px; color: #c9d1d9; margin-top: 6px;">
                    Майнери можуть підключатися як локально, так і з інших ПК у локальній мережі або через Інтернет:
                </div>
                <div class="code-box">HTTP Node RPC:   http://127.0.0.1:8333 (Локально)</div>
                <div class="code-box">Stratum Pool:   Публічний Tensorix Stratum: не підтверджено</div>
                <div class="code-box">Stratum LAN:    Локальний Stratum: 127.0.0.1:3333</div>
                <div style="margin-top: 14px;">
                    <a href="/publish" style="display: inline-block; background: #1f6feb; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px;">🚀 Відкрити помічник публікації (GitHub, Bitcointalk, Pools) →</a>
                </div>
            </div>

            <div class="table-card">
                <h3 style="margin-top: 0; margin-bottom: 16px; color: #f0f6fc;">Останні Знайдені Блоки</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Блок</th>
                            <th>Хеш Блоку</th>
                            <th>Складність</th>
                            <th>Nonce</th>
                            <th>Транзакції</th>
                            <th>Винагорода</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html


@app.get("/publish", response_class=HTMLResponse)
def publish_assistant():
    return "<h1>Tensorix experimental reference</h1><p>No verified CUDA release or public pool deployment is included. See AUDIT.md for fee mechanisms, validation changes and remaining release blockers.</p>"


@app.get("/api")
def root_api():
    return {
        "network": "Tensorix experimental reference",
        "ticker": "TNX",
        "version": "1.0.0",
        "status": "experimental"
    }


@app.get("/info")
def get_node_info():
    if not blockchain.chain:
        return {"status": "uninitialized", "blocks": 0}
    
    latest = blockchain.get_latest_block()
    return {
        "network": "Tensorix Network",
        "ticker": "TNX",
        "height": latest.index,
        "latest_block_hash": latest.hash,
        "current_difficulty": latest.difficulty,
        "next_difficulty": blockchain.get_next_difficulty(),
        "mempool_tx_count": len(blockchain.mempool),
        "total_mined_supply_tnx": (sum(tx.amount for b in blockchain.chain for tx in b.transactions if tx.is_coinbase())) / COIN,
        "peers_count": len(peers)
    }


@app.get("/block/latest")
def get_latest_block():
    if not blockchain.chain:
        raise HTTPException(status_code=404, detail="Blockchain is empty")
    return blockchain.get_latest_block().to_dict()


@app.get("/block/{identifier}")
def get_block(identifier: str):
    if identifier.isdigit():
        idx = int(identifier)
        if 0 <= idx < len(blockchain.chain):
            return blockchain.chain[idx].to_dict()
        raise HTTPException(status_code=404, detail=f"Block index #{idx} not found")
    else:
        for b in blockchain.chain:
            if b.hash == identifier:
                return b.to_dict()
        raise HTTPException(status_code=404, detail=f"Block hash {identifier} not found")


@app.get("/balance/{address}")
def get_balance(address: str):
    balance_units = blockchain.get_balance(address)
    nonce = blockchain.get_account_nonce(address)
    return {
        "address": address,
        "balance_tnx": balance_units / COIN,
        "balance_atomic": balance_units,
        "nonce": nonce
    }


@app.get("/mining/template")
def get_mining_template(address: str = Query(..., description="Miner TNX payout address")):
    if not valid_address(address):
        raise HTTPException(status_code=400, detail="Complete TNX payout address required")
    
    if not blockchain.chain:
        raise HTTPException(status_code=400, detail="Genesis block not yet initialized on node")
    
    template = blockchain.get_block_template(address)
    return template


@app.post("/mining/submit")
def submit_mined_block(req: BlockSubmitRequest):
    try:
        block = Block.from_dict(req.model_dump())
        success, msg = blockchain.submit_block(block)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail="Invalid block encoding") from exc
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "block_hash": block.hash, "index": block.index}


@app.post("/tx/send")
def send_transaction(req: SendTxRequest):
    if req.fee < MIN_TX_FEE:
        raise HTTPException(
            status_code=400,
            detail=f"Transaction fee too low: {req.fee / COIN:.2f} TNX provided, minimum required is {MIN_TX_FEE / COIN:.2f} TNX."
        )
    tx = Transaction(
        sender=req.sender,
        recipient=req.recipient,
        amount=req.amount,
        fee=req.fee,
        nonce=req.nonce,
        public_key=req.public_key,
        signature=req.signature
    )
    success, msg = blockchain.add_transaction(tx)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "txid": tx.txid, "message": msg}


@app.get("/mempool")
def get_mempool():
    return {
        "count": len(blockchain.mempool),
        "transactions": [tx.to_dict() for tx in blockchain.mempool.values()]
    }


@app.get("/p2p/blocks")
def p2p_get_blocks(since: int = 0):
    return [b.to_dict() for b in blockchain.chain[since:since + 100]]


def start_node(host: str = "127.0.0.1", port: int = 8333):
    print(f"Starting Tensorix Node on http://{host}:{port}...")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_node()

