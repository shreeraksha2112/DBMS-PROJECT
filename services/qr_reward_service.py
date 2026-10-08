from datetime import datetime
from io import BytesIO

import qrcode
from sqlalchemy.exc import IntegrityError

from repositories.db import db
from repositories.models import QRClaim, QREvent
from services.verification_service import create_notification, log_audit_event
from services.wallet_service import credit_wallet


class QRRewardError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def create_qr_image(token):
    image = qrcode.make(token)
    output = BytesIO()
    image.save(output, format='PNG')
    output.seek(0)
    return output


def claim_qr_reward(user_id, token):
    event = QREvent.query.filter_by(qr_token=token).first()
    if not event:
        raise QRRewardError('Invalid event QR code', 404)
    if not event.active:
        raise QRRewardError('This event QR code is no longer active', 410)
    if event.expires_at <= datetime.utcnow():
        raise QRRewardError('This event QR code has expired', 410)
    if QRClaim.query.filter_by(event_id=event.event_id, user_id=user_id).first():
        raise QRRewardError('You have already claimed this event reward', 409)

    db.session.add(QRClaim(event_id=event.event_id, user_id=user_id))
    try:
        db.session.flush()
        wallet = credit_wallet(
            user_id,
            event.reward_points,
            reference_id=event.event_id,
            transaction_type='qr_reward',
        )
        create_notification(
            user_id,
            'reward',
            f"You earned {event.reward_points:g} points at {event.business_name}: {event.event_name}.",
        )
        log_audit_event(user_id, 'qr_reward_claimed', 'qr_event', event.event_id, event.event_name)
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise QRRewardError('You have already claimed this event reward', 409) from exc
    except Exception:
        db.session.rollback()
        raise

    return {
        'verified': True,
        'message': 'Event QR verified and reward added to your wallet',
        'event_id': event.event_id,
        'business_name': event.business_name,
        'event_name': event.event_name,
        'points_awarded': float(event.reward_points),
        'wallet_balance': float(wallet.current_balance),
    }