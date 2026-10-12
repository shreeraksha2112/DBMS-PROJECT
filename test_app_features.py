import unittest
from datetime import datetime, timedelta
import jwt
from sqlalchemy import create_engine, inspect, text

from app import create_app, ensure_schema_compatibility
from repositories.db import db
from repositories.models import (
    Role, ActivityType, ImpactFactor, Challenge, Reward, User, EcoActivity,
    QREvent, QRClaim, Notification,
)


class TestConfig:
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class EcoSphereFeatureTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()

            role = Role(role_name='User')
            db.session.add(role)
            db.session.flush()

            activity = ActivityType(name='Cycling', unit='km', base_points=10.0, verification_required=False)
            db.session.add(activity)
            db.session.flush()
            db.session.add(ImpactFactor(activity_id=activity.activity_id, metric_type='CO2e (kg)', factor_value=0.2))

            db.session.add(
                Challenge(
                    title='Cycling Century',
                    type='personal',
                    target_value=100.0,
                    reward_points=50.0,
                    start_date=datetime.utcnow(),
                    end_date=datetime.utcnow() + timedelta(days=30),
                )
            )

            db.session.add(Reward(name='Sample Reward', points_required=10.0, stock=5, tier=1, active=True))
            db.session.commit()

    def test_startup_migrates_legacy_schema(self):
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE users ('
                'user_id INTEGER PRIMARY KEY, role_id INTEGER NOT NULL, '
                'name VARCHAR(100) NOT NULL, email VARCHAR(150) NOT NULL, '
                'password_hash VARCHAR(255) NOT NULL, eco_score FLOAT, '
                'level INTEGER, created_at DATETIME)'
            ))
            connection.execute(text(
                'CREATE TABLE eco_activities ('
                'record_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, '
                'activity_id INTEGER NOT NULL, quantity FLOAT NOT NULL, '
                'points FLOAT NOT NULL, status VARCHAR(50), activity_date DATETIME)'
            ))

        ensure_schema_compatibility(engine)
        user_columns = {column['name'] for column in inspect(engine).get_columns('users')}
        activity_columns = {column['name'] for column in inspect(engine).get_columns('eco_activities')}
        self.assertIn('account_status', user_columns)
        self.assertTrue({'is_flagged', 'risk_score', 'flag_reason'}.issubset(activity_columns))
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT account_status FROM users')).fetchall(), [])
        engine.dispose()

    def test_user_activity_wallet_impact_and_leaderboard(self):
        register = self.client.post('/api/auth/register', json={
            'name': 'Test User',
            'email': 'test.user@example.com',
            'password': 'password123'
        })
        self.assertEqual(register.status_code, 201, register.get_data(as_text=True))

        login = self.client.post('/api/auth/login', json={
            'email': 'test.user@example.com',
            'password': 'password123'
        })
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))
        token = login.get_json()['token']
        headers = {'Authorization': f'Bearer {token}'}

        activity = self.client.post('/api/activities/', json={
            'activity_id': 1,
            'quantity': 5.0
        }, headers=headers)
        self.assertEqual(activity.status_code, 201, activity.get_data(as_text=True))
        self.assertGreaterEqual(activity.get_json()['points_earned'], 50.0)

        dashboard = self.client.get('/api/dashboard', headers=headers)
        self.assertEqual(dashboard.status_code, 200)
        self.assertGreaterEqual(dashboard.get_json()['wallet']['balance'], 50.0)

        impact = self.client.get('/api/impact', headers=headers)
        self.assertEqual(impact.status_code, 200, impact.get_data(as_text=True))
        self.assertIn('total_impact', impact.get_json())

        leaderboard = self.client.get('/api/leaderboard', headers=headers)
        self.assertEqual(leaderboard.status_code, 200, leaderboard.get_data(as_text=True))
        self.assertIn('leaderboard', leaderboard.get_json())

        rewards = self.client.get('/api/rewards/', headers=headers)
        self.assertEqual(rewards.status_code, 200, rewards.get_data(as_text=True))
        reward_id = rewards.get_json()['rewards'][0]['reward_id']

        redemption = self.client.post(f'/api/rewards/{reward_id}/redeem', headers=headers)
        self.assertEqual(redemption.status_code, 200, redemption.get_data(as_text=True))

    def test_challenge_progress_completes_and_awards_bonus(self):
        registration = self.client.post('/api/auth/register', json={
            'name': 'Challenge Progress User',
            'email': 'challenge.progress@example.com',
            'password': 'userpass'
        })
        self.assertEqual(registration.status_code, 201)
        login = self.client.post('/api/auth/login', json={
            'email': 'challenge.progress@example.com',
            'password': 'userpass'
        })
        self.assertEqual(login.status_code, 200)
        headers = {'Authorization': 'Bearer ' + login.get_json()['token']}

        challenges = self.client.get('/api/challenges/', headers=headers)
        self.assertEqual(challenges.status_code, 200)
        challenge = challenges.get_json()['challenges'][0]
        self.assertEqual(challenge['status'], 'available')
        self.assertFalse(challenge['joined'])

        joined = self.client.post(
            f"/api/challenges/{challenge['challenge_id']}/join",
            headers=headers,
        )
        self.assertEqual(joined.status_code, 201, joined.get_data(as_text=True))
        self.assertIn('Log eligible activities', joined.get_json()['message'])

        progress = self.client.post(
            '/api/activities/',
            json={'activity_id': 1, 'quantity': 40},
            headers=headers,
        )
        self.assertEqual(progress.status_code, 201)
        challenges = self.client.get('/api/challenges/', headers=headers).get_json()['challenges']
        self.assertEqual(challenges[0]['progress'], 40)
        self.assertEqual(challenges[0]['status'], 'active')

        completion = self.client.post(
            '/api/activities/',
            json={'activity_id': 1, 'quantity': 60},
            headers=headers,
        )
        self.assertEqual(completion.status_code, 201)
        challenges = self.client.get('/api/challenges/', headers=headers).get_json()['challenges']
        self.assertEqual(challenges[0]['progress'], 100)
        self.assertEqual(challenges[0]['status'], 'completed')
        wallet = self.client.get('/api/wallet', headers=headers)
        self.assertEqual(wallet.status_code, 200)
        self.assertEqual(wallet.get_json()['balance'], 1050)
        transactions = wallet.get_json()['transactions']
        self.assertTrue(any(tx['transaction_type'] == 'challenge_reward' for tx in transactions))

    def test_history_notifications_badges_leaderboard_and_reminders(self):
        registration = self.client.post('/api/auth/register', json={
            'name': 'History Feature User',
            'email': 'history.features@example.com',
            'password': 'userpass'
        })
        self.assertEqual(registration.status_code, 201)
        login = self.client.post('/api/auth/login', json={
            'email': 'history.features@example.com',
            'password': 'userpass'
        })
        headers = {'Authorization': 'Bearer ' + login.get_json()['token']}
        user_id = registration.get_json()['user_id']

        types = self.client.get('/api/activities/types', headers=headers)
        self.assertEqual(types.status_code, 200)
        self.assertEqual(types.get_json()['activity_types'][0]['name'], 'Cycling')

        activity = self.client.post(
            '/api/activities/',
            json={'activity_id': 1, 'quantity': 5},
            headers=headers,
        )
        self.assertEqual(activity.status_code, 201)
        filtered = self.client.get(
            '/api/activities/?activity_id=1&status=approved',
            headers=headers,
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.get_json()['summary']['count'], 1)
        self.assertEqual(filtered.get_json()['summary']['total_quantity'], 5)
        self.assertEqual(filtered.get_json()['summary']['total_points'], 50)
        invalid_filter = self.client.get('/api/activities/?status=unknown', headers=headers)
        self.assertEqual(invalid_filter.status_code, 400)

        badges = self.client.get('/api/badges', headers=headers)
        self.assertEqual(badges.status_code, 200)
        first_steps = next(item for item in badges.get_json()['badges'] if item['name'] == 'First Steps')
        self.assertTrue(first_steps['earned'])

        rewards = self.client.get('/api/rewards/', headers=headers).get_json()['rewards']
        redemption = self.client.post(f"/api/rewards/{rewards[0]['reward_id']}/redeem", headers=headers)
        self.assertEqual(redemption.status_code, 200)
        history = self.client.get('/api/rewards/history', headers=headers)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.get_json()['total_redemptions'], 1)
        self.assertEqual(history.get_json()['total_points_spent'], rewards[0]['points_required'])

        challenges = self.client.get('/api/challenges/', headers=headers).get_json()['challenges']
        challenge = next(item for item in challenges if item['title'] == 'Cycling Century')
        joined = self.client.post(f"/api/challenges/{challenge['challenge_id']}/join", headers=headers)
        self.assertEqual(joined.status_code, 201)
        leaderboard = self.client.get(
            f"/api/challenges/{challenge['challenge_id']}/leaderboard",
            headers=headers,
        )
        self.assertEqual(leaderboard.status_code, 200)
        self.assertTrue(leaderboard.get_json()['leaderboard'][0]['is_current_user'])

        with self.app.app_context():
            reminder_challenge = Challenge(
                title='Upcoming Community Cleanup',
                type='personal',
                target_value=10,
                reward_points=20,
                start_date=datetime.utcnow() + timedelta(hours=12),
                end_date=datetime.utcnow() + timedelta(days=2),
            )
            db.session.add(reminder_challenge)
            db.session.commit()
            reminder_challenge_id = reminder_challenge.challenge_id
        reminder = self.client.put(
            f'/api/challenges/{reminder_challenge_id}/reminder',
            headers=headers,
        )
        self.assertEqual(reminder.status_code, 200)
        self.assertTrue(reminder.get_json()['reminder_enabled'])
        self.client.get('/api/challenges/', headers=headers)
        self.client.get('/api/challenges/', headers=headers)
        with self.app.app_context():
            reminder_notifications = Notification.query.filter_by(
                user_id=user_id,
                notification_type='challenge',
            ).all()
            self.assertEqual(len(reminder_notifications), 1)

        notifications = self.client.get('/api/notifications', headers=headers)
        self.assertEqual(notifications.status_code, 200)
        self.assertGreater(notifications.get_json()['unread_count'], 0)
        notification_id = notifications.get_json()['notifications'][0]['notification_id']
        marked = self.client.patch(f'/api/notifications/{notification_id}/read', headers=headers)
        self.assertEqual(marked.status_code, 200)
        all_read = self.client.patch('/api/notifications/read-all', headers=headers)
        self.assertEqual(all_read.status_code, 200)
        unread = self.client.get('/api/notifications', headers=headers)
        self.assertEqual(unread.get_json()['unread_count'], 0)

    def test_admin_can_approve_and_reject_activities(self):
        with self.app.app_context():
            activity_type = ActivityType.query.filter_by(name='Cycling').first()
            activity_type.verification_required = True
            admin_role = Role.query.filter_by(role_name='Admin').first()
            if admin_role is None:
                admin_role = Role(role_name='Admin')
                db.session.add(admin_role)
                db.session.commit()

        admin_registration = self.client.post('/api/auth/register', json={
            'name': 'Review Admin',
            'email': 'review.admin@example.com',
            'password': 'adminpass'
        })
        self.assertEqual(admin_registration.status_code, 201)
        with self.app.app_context():
            admin_user = db.session.query(__import__('repositories.models', fromlist=['User']).User).filter_by(email='review.admin@example.com').first()
            admin_user.role_id = Role.query.filter_by(role_name='Admin').first().role_id
            db.session.commit()

        user_registration = self.client.post('/api/auth/register', json={
            'name': 'Activity Reviewer Test',
            'email': 'review.user@example.com',
            'password': 'userpass'
        })
        self.assertEqual(user_registration.status_code, 201)
        user_login = self.client.post('/api/auth/login', json={
            'email': 'review.user@example.com',
            'password': 'userpass'
        })
        user_headers = {'Authorization': 'Bearer ' + user_login.get_json()['token']}

        first = self.client.post('/api/activities/', json={'activity_id': 1, 'quantity': 2}, headers=user_headers)
        second = self.client.post('/api/activities/', json={'activity_id': 1, 'quantity': 3}, headers=user_headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.get_json()['status'], 'pending')
        self.assertEqual(second.status_code, 201)

        admin_login = self.client.post('/api/auth/admin-login', json={
            'email': 'review.admin@example.com',
            'password': 'adminpass'
        })
        admin_headers = {'Authorization': 'Bearer ' + admin_login.get_json()['token']}

        unauthorized = self.client.get('/api/admin/activities/pending', headers=user_headers)
        self.assertEqual(unauthorized.status_code, 403)
        pending = self.client.get('/api/admin/activities/pending', headers=admin_headers)
        self.assertEqual(pending.status_code, 200)
        activities = pending.get_json()['activities']
        self.assertEqual(len(activities), 2)
        approved_id, rejected_id = [item['record_id'] for item in activities]

        forbidden_flag = self.client.patch(
            f'/api/admin/activities/{approved_id}/flag',
            json={'flagged': True, 'reason': 'Needs review'},
            headers=user_headers,
        )
        self.assertEqual(forbidden_flag.status_code, 403)
        missing_reason = self.client.patch(
            f'/api/admin/activities/{approved_id}/flag',
            json={'flagged': True},
            headers=admin_headers,
        )
        self.assertEqual(missing_reason.status_code, 400)
        flagged = self.client.patch(
            f'/api/admin/activities/{approved_id}/flag',
            json={'flagged': True, 'reason': 'Unusual quantity pattern'},
            headers=admin_headers,
        )
        self.assertEqual(flagged.status_code, 200, flagged.get_data(as_text=True))
        self.assertTrue(flagged.get_json()['is_flagged'])

        pending_after_flag = self.client.get('/api/admin/activities/pending', headers=admin_headers)
        flagged_activity = next(item for item in pending_after_flag.get_json()['activities'] if item['record_id'] == approved_id)
        self.assertEqual(flagged_activity['status'], 'flagged')
        self.assertEqual(flagged_activity['reason'], 'Unusual quantity pattern')

        cleared = self.client.patch(
            f'/api/admin/activities/{approved_id}/flag',
            json={'flagged': False},
            headers=admin_headers,
        )
        self.assertEqual(cleared.status_code, 200, cleared.get_data(as_text=True))
        self.assertFalse(cleared.get_json()['is_flagged'])
        self.assertEqual(cleared.get_json()['status'], 'pending')
        flagged = self.client.patch(
            f'/api/admin/activities/{approved_id}/flag',
            json={'flagged': True, 'reason': 'Unusual quantity pattern'},
            headers=admin_headers,
        )
        self.assertEqual(flagged.status_code, 200)

        approve = self.client.post(f'/api/admin/activities/{approved_id}/review', json={'decision': 'approved'}, headers=admin_headers)
        self.assertEqual(approve.status_code, 200, approve.get_data(as_text=True))
        self.assertFalse(approve.get_json()['result'].get('is_flagged', False))
        duplicate = self.client.post(f'/api/admin/activities/{approved_id}/review', json={'decision': 'approved'}, headers=admin_headers)
        self.assertEqual(duplicate.status_code, 409)

        reject = self.client.post(f'/api/admin/activities/{rejected_id}/review', json={'decision': 'rejected'}, headers=admin_headers)
        self.assertEqual(reject.status_code, 200, reject.get_data(as_text=True))

        wallet = self.client.get('/api/wallet', headers=user_headers)
        self.assertEqual(wallet.get_json()['balance'], 30)

    def test_platform_feature_suite(self):
        with self.app.app_context():
            admin_role = Role.query.filter_by(role_name='Admin').first()
            if admin_role is None:
                admin_role = Role(role_name='Admin')
                db.session.add(admin_role)
                db.session.commit()

            admin_user = self.client.post('/api/auth/register', json={
                'name': 'Admin User',
                'email': 'admin@example.com',
                'password': 'adminpass'
            })
            self.assertEqual(admin_user.status_code, 201)
            user = db.session.query(__import__('repositories.models', fromlist=['User']).User).filter_by(email='admin@example.com').first()
            user.role_id = admin_role.role_id
            db.session.commit()

        normal = self.client.post('/api/auth/register', json={
            'name': 'Feature User',
            'email': 'feature.user@example.com',
            'password': 'password123'
        })
        self.assertEqual(normal.status_code, 201, normal.get_data(as_text=True))

        regular_login = self.client.post('/api/auth/login', json={
            'email': 'feature.user@example.com',
            'password': 'password123'
        })
        self.assertEqual(regular_login.status_code, 200, regular_login.get_data(as_text=True))
        regular_headers = {'Authorization': f"Bearer {regular_login.get_json()['token']}"}

        suspicious_activity = self.client.post('/api/activities/', json={
            'activity_id': 1,
            'quantity': 2500.0
        }, headers=regular_headers)
        self.assertEqual(suspicious_activity.status_code, 201, suspicious_activity.get_data(as_text=True))

        impact = self.client.get('/api/impact', headers=regular_headers)
        self.assertEqual(impact.status_code, 200)
        self.assertIn('forecast', impact.get_json())
        self.assertIn('trend', impact.get_json())

        notifications = self.client.get('/api/notifications', headers=regular_headers)
        self.assertEqual(notifications.status_code, 200, notifications.get_data(as_text=True))
        self.assertIn('notifications', notifications.get_json())

        admin_login = self.client.post('/api/auth/admin-login', json={
            'email': 'admin@example.com',
            'password': 'adminpass'
        })
        self.assertEqual(admin_login.status_code, 200, admin_login.get_data(as_text=True))
        admin_headers = {'Authorization': f"Bearer {admin_login.get_json()['token']}"}

        moderation = self.client.get('/api/admin/moderation', headers=admin_headers)
        self.assertEqual(moderation.status_code, 200, moderation.get_data(as_text=True))
        self.assertIn('flagged', moderation.get_json())

        logs = self.client.get('/api/admin/audit-logs', headers=admin_headers)
        self.assertEqual(logs.status_code, 200, logs.get_data(as_text=True))
        self.assertIn('audit_logs', logs.get_json())

        qr = self.client.post('/api/verify/qr', json={'qr_token': 'cycling-qr'}, headers=regular_headers)
        self.assertEqual(qr.status_code, 200, qr.get_data(as_text=True))
        self.assertTrue(qr.get_json()['verified'])

    def test_business_qr_event_rewards_once(self):
        with self.app.app_context():
            admin_role = Role.query.filter_by(role_name='Admin').first()
            if admin_role is None:
                admin_role = Role(role_name='Admin')
                db.session.add(admin_role)
                db.session.commit()

        admin_registration = self.client.post('/api/auth/register', json={
            'name': 'QR Event Admin',
            'email': 'qr.admin@example.com',
            'password': 'adminpass'
        })
        self.assertEqual(admin_registration.status_code, 201)
        with self.app.app_context():
            admin_user = db.session.query(__import__('repositories.models', fromlist=['User']).User).filter_by(email='qr.admin@example.com').first()
            admin_user.role_id = Role.query.filter_by(role_name='Admin').first().role_id
            db.session.commit()

        registration = self.client.post('/api/auth/register', json={
            'name': 'QR Event User',
            'email': 'qr.user@example.com',
            'password': 'userpass'
        })
        self.assertEqual(registration.status_code, 201)

        admin_login = self.client.post('/api/auth/admin-login', json={
            'email': 'qr.admin@example.com',
            'password': 'adminpass'
        })
        user_login = self.client.post('/api/auth/login', json={
            'email': 'qr.user@example.com',
            'password': 'userpass'
        })
        admin_headers = {'Authorization': f"Bearer {admin_login.get_json()['token']}"}
        user_headers = {'Authorization': f"Bearer {user_login.get_json()['token']}"}

        forbidden = self.client.post('/api/admin/qr-events', json={
            'business_name': 'Green Market',
            'event_name': 'Community Cleanup',
            'reward_points': 75,
            'expires_in_hours': 24
        }, headers=user_headers)
        self.assertEqual(forbidden.status_code, 403)

        created = self.client.post('/api/admin/qr-events', json={
            'business_name': 'Green Market',
            'event_name': 'Community Cleanup',
            'reward_points': 75,
            'expires_in_hours': 24
        }, headers=admin_headers)
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        event = created.get_json()['qr_event']
        self.assertEqual(event['business_name'], 'Green Market')
        self.assertEqual(event['reward_points'], 75)

        qr_image = self.client.get(f"/api/admin/qr-events/{event['event_id']}/qr", headers=admin_headers)
        self.assertEqual(qr_image.status_code, 200)
        self.assertEqual(qr_image.mimetype, 'image/png')

        claim = self.client.post('/api/verify/qr', json={'qr_token': event['qr_token']}, headers=user_headers)
        self.assertEqual(claim.status_code, 200, claim.get_data(as_text=True))
        self.assertEqual(claim.get_json()['points_awarded'], 75)

        history = self.client.get('/api/qr-rewards/history', headers=user_headers)
        self.assertEqual(history.status_code, 200, history.get_data(as_text=True))
        history_data = history.get_json()
        self.assertEqual(history_data['total_claims'], 1)
        self.assertEqual(history_data['total_points'], 75)
        self.assertEqual(history_data['claims'][0]['event_name'], 'Community Cleanup')

        duplicate = self.client.post('/api/verify/qr', json={'qr_token': event['qr_token']}, headers=user_headers)
        self.assertEqual(duplicate.status_code, 409)

        deactivated = self.client.patch(f"/api/admin/qr-events/{event['event_id']}", json={'active': False}, headers=admin_headers)
        self.assertEqual(deactivated.status_code, 200, deactivated.get_data(as_text=True))
        inactive_claim = self.client.post('/api/verify/qr', json={'qr_token': event['qr_token']}, headers=user_headers)
        self.assertEqual(inactive_claim.status_code, 410)

        wallet = self.client.get('/api/wallet', headers=user_headers)
        self.assertEqual(wallet.status_code, 200)
        self.assertEqual(wallet.get_json()['balance'], 75)

    def test_admin_user_management(self):
        with self.app.app_context():
            admin_role = Role.query.filter_by(role_name='Admin').first()
            if admin_role is None:
                admin_role = Role(role_name='Admin')
                db.session.add(admin_role)
                db.session.commit()

            admin = self.client.post('/api/auth/register', json={
                'name': 'Admin Manager',
                'email': 'admin.manager@example.com',
                'password': 'adminpass'
            })
            self.assertEqual(admin.status_code, 201)
            admin_user = db.session.query(__import__('repositories.models', fromlist=['User']).User).filter_by(email='admin.manager@example.com').first()
            admin_user.role_id = admin_role.role_id
            db.session.commit()

        user = self.client.post('/api/auth/register', json={
            'name': 'Progress User',
            'email': 'progress.user@example.com',
            'password': 'userpass'
        })
        self.assertEqual(user.status_code, 201)

        admin_login = self.client.post('/api/auth/admin-login', json={
            'email': 'admin.manager@example.com',
            'password': 'adminpass'
        })
        self.assertEqual(admin_login.status_code, 200)
        admin_headers = {'Authorization': f"Bearer {admin_login.get_json()['token']}"}

        list_users = self.client.get('/api/admin/users', headers=admin_headers)
        self.assertEqual(list_users.status_code, 200)
        payload = list_users.get_json()
        self.assertIn('users', payload)
        self.assertGreaterEqual(len(payload['users']), 2)

        late_registration = self.client.post('/api/auth/register', json={
            'name': 'Newly Registered User',
            'email': 'newly.registered@example.com',
            'password': 'userpass'
        })
        self.assertEqual(late_registration.status_code, 201)
        refreshed_users = self.client.get('/api/admin/users', headers=admin_headers)
        self.assertEqual(refreshed_users.status_code, 200)
        refreshed_emails = [item['email'] for item in refreshed_users.get_json()['users']]
        self.assertIn('newly.registered@example.com', refreshed_emails)
        self.assertEqual(refreshed_emails[0], 'newly.registered@example.com')

        user_login = self.client.post('/api/auth/login', json={
            'email': 'newly.registered@example.com',
            'password': 'userpass'
        })
        user_headers = {'Authorization': 'Bearer ' + user_login.get_json()['token']}
        forbidden_export = self.client.get('/api/admin/exports/users.csv', headers=user_headers)
        self.assertEqual(forbidden_export.status_code, 403)
        for dataset, expected_header in (
            ('users', 'user_id,name,email'),
            ('activities', 'record_id,user_id,user_name'),
            ('qr-claims', 'claim_id,event_id,business_name'),
        ):
            exported = self.client.get(f'/api/admin/exports/{dataset}.csv', headers=admin_headers)
            self.assertEqual(exported.status_code, 200, exported.get_data(as_text=True))
            self.assertEqual(exported.mimetype, 'text/csv')
            self.assertIn(expected_header, exported.get_data(as_text=True))

        progress = self.client.get('/api/admin/users/2/progress', headers=admin_headers)
        self.assertEqual(progress.status_code, 200)
        self.assertIn('progress', progress.get_json())

        reset = self.client.post('/api/admin/users/2/reset-password', json={'password': 'newsecret'}, headers=admin_headers)
        self.assertEqual(reset.status_code, 200, reset.get_data(as_text=True))

        login = self.client.post('/api/auth/login', json={
            'email': 'progress.user@example.com',
            'password': 'newsecret'
        })
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))

        terminate = self.client.post('/api/admin/users/2/terminate', headers=admin_headers)
        self.assertEqual(terminate.status_code, 200, terminate.get_data(as_text=True))

        disabled = self.client.post('/api/auth/login', json={
            'email': 'progress.user@example.com',
            'password': 'newsecret'
        })
        self.assertEqual(disabled.status_code, 403)

    def test_admin_analytics_requires_admin_and_returns_chart_series(self):
        admin_registration = self.client.post('/api/auth/register', json={
            'name': 'Analytics Admin',
            'email': 'analytics.admin@example.com',
            'password': 'adminpass'
        })
        self.assertEqual(admin_registration.status_code, 201)
        with self.app.app_context():
            admin = User.query.filter_by(email='analytics.admin@example.com').first()
            admin_role = Role.query.filter_by(role_name='Admin').first()
            if admin_role is None:
                admin_role = Role(role_name='Admin')
                db.session.add(admin_role)
                db.session.flush()
            admin.role_id = admin_role.role_id
            db.session.commit()
            admin_id = admin.user_id

        user_registration = self.client.post('/api/auth/register', json={
            'name': 'Analytics User',
            'email': 'analytics.user@example.com',
            'password': 'userpass'
        })
        self.assertEqual(user_registration.status_code, 201)
        user_login = self.client.post('/api/auth/login', json={
            'email': 'analytics.user@example.com',
            'password': 'userpass'
        })
        user_headers = {'Authorization': 'Bearer ' + user_login.get_json()['token']}
        admin_login = self.client.post('/api/auth/admin-login', json={
            'email': 'analytics.admin@example.com',
            'password': 'adminpass'
        })
        admin_headers = {'Authorization': 'Bearer ' + admin_login.get_json()['token']}

        with self.app.app_context():
            user = User.query.filter_by(email='analytics.user@example.com').first()
            activity_type = ActivityType.query.filter_by(name='Cycling').first()
            event = QREvent(
                business_name='Green Market',
                event_name='Community Cleanup',
                qr_token='analytics-test-token',
                reward_points=25,
                expires_at=datetime.utcnow() + timedelta(days=1),
                created_by=admin_id,
            )
            db.session.add(event)
            db.session.flush()
            db.session.add(EcoActivity(
                user_id=user.user_id,
                activity_id=activity_type.activity_id,
                quantity=2,
                points=20,
                status='approved',
            ))
            db.session.add(QRClaim(event_id=event.event_id, user_id=user.user_id))
            db.session.commit()

        forbidden = self.client.get('/api/admin/analytics?days=7', headers=user_headers)
        self.assertEqual(forbidden.status_code, 403)
        invalid_range = self.client.get('/api/admin/analytics?days=14', headers=admin_headers)
        self.assertEqual(invalid_range.status_code, 400)
        response = self.client.get('/api/admin/analytics?days=7', headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        analytics = response.get_json()
        self.assertEqual(analytics['days'], 7)
        self.assertEqual(len(analytics['labels']), 7)
        self.assertEqual(len(analytics['daily']['users']), 7)
        self.assertEqual(analytics['daily']['activities'][-1], 1)
        self.assertEqual(analytics['daily']['qr_claims'][-1], 1)
        self.assertIn({'status': 'approved', 'count': 1}, analytics['activity_status'])
        self.assertEqual(analytics['qr_events'][0], {
            'label': 'Green Market: Community Cleanup',
            'claims': 1,
        })

    def test_dedicated_admin_login_security(self):
        register = self.client.post('/api/auth/register', json={
            'name': 'Admin Login User',
            'email': 'admin.login@example.com',
            'password': 'securepass'
        })
        self.assertEqual(register.status_code, 201)

        page = self.client.get('/admin/login')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Content-Security-Policy', page.headers)
        self.assertEqual(page.headers.get('Cache-Control'), 'no-store')

        rejected = self.client.post('/api/auth/admin-login', json={
            'email': 'admin.login@example.com',
            'password': 'securepass'
        })
        self.assertEqual(rejected.status_code, 401)

        with self.app.app_context():
            admin_role = Role.query.filter_by(role_name='Admin').first()
            if admin_role is None:
                admin_role = Role(role_name='Admin')
                db.session.add(admin_role)
                db.session.commit()
            user = db.session.query(__import__('repositories.models', fromlist=['User']).User).filter_by(email='admin.login@example.com').first()
            user.role_id = admin_role.role_id
            db.session.commit()

        standard_login = self.client.post('/api/auth/login', json={
            'email': 'admin.login@example.com',
            'password': 'securepass'
        })
        self.assertEqual(standard_login.status_code, 401)

        accepted = self.client.post('/api/auth/admin-login', json={
            'email': 'admin.login@example.com',
            'password': 'securepass'
        })
        self.assertEqual(accepted.status_code, 200, accepted.get_data(as_text=True))
        token = accepted.get_json()['token']
        claims = jwt.decode(token, self.app.config['SECRET_KEY'], algorithms=['HS256'])
        self.assertEqual(claims['role'], 'Admin')
        self.assertLessEqual(claims['exp'] - claims['iat'], 3600)

        with self.app.app_context():
            user = db.session.query(__import__('repositories.models', fromlist=['User']).User).filter_by(email='admin.login@example.com').first()
            user.account_status = 'terminated'
            db.session.commit()

        protected = self.client.get('/api/admin/users', headers={
            'Authorization': f"Bearer {token}"
        })
        self.assertEqual(protected.status_code, 401)


if __name__ == '__main__':
    unittest.main()
