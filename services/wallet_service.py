from repositories.db import db
from repositories.models import Wallet, PointTransaction


def get_wallet_summary(user_id):
    wallet = Wallet.query.get(user_id)
    balance = float(wallet.current_balance) if wallet else 0.0
    transactions = PointTransaction.query.filter_by(user_id=user_id).order_by(PointTransaction.created_at.desc()).limit(10).all()
    return {
        "user_id": user_id,
        "balance": balance,
        "transactions": [
            {
                "transaction_id": tx.transaction_id,
                "amount": float(tx.amount),
                "transaction_type": tx.transaction_type,
                "reference_id": tx.reference_id,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx in transactions
        ],
    }


def credit_wallet(user_id, amount, reference_id=None, transaction_type='credit'):
    amount = float(amount)
    if amount <= 0:
        return None

    wallet = Wallet.query.get(user_id)
    if wallet is None:
        wallet = Wallet(user_id=user_id, current_balance=0.0)
        db.session.add(wallet)

    wallet.current_balance += amount

    transaction = PointTransaction(
        user_id=user_id,
        amount=amount,
        transaction_type=transaction_type,
        reference_id=reference_id,
    )
    db.session.add(transaction)
    db.session.flush()
    return wallet


def debit_wallet(user_id, amount, reference_id=None, transaction_type='debit'):
    amount = float(amount)
    if amount <= 0:
        return None

    wallet = Wallet.query.get(user_id)
    if wallet is None or wallet.current_balance < amount:
        raise ValueError('Insufficient points')

    wallet.current_balance -= amount

    transaction = PointTransaction(
        user_id=user_id,
        amount=amount,
        transaction_type=transaction_type,
        reference_id=reference_id,
    )
    db.session.add(transaction)
    db.session.flush()
    return wallet
