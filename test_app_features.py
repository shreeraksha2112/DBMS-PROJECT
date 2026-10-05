import unittest
from datetime import datetime, timedelta

from app import create_app
from repositories.db import db
from repositories.models import Role, ActivityType, ImpactFactor, Challenge, Reward


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


if __name__ == '__main__':
    unittest.main()
