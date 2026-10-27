from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .views import PAGES, ensure_demo_user


class FullAdminAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='root-admin',
            email='root@example.com',
            password='AdminPass123!',
        )
        self.regular_user = User.objects.create_user(
            username='member',
            email='member@example.com',
            password='MemberPass123!',
        )

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse('index_html'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('index_html')}",
            fetch_redirect_response=False,
        )

    def test_non_admin_is_denied_every_admin_page(self):
        self.client.force_login(self.regular_user)

        self.assertEqual(self.client.get(reverse('index_html')).status_code, 403)
        for page_name in PAGES:
            with self.subTest(page_name=page_name):
                response = self.client.get(f'/{page_name}.html')
                self.assertEqual(response.status_code, 403)

    def test_superuser_can_open_every_admin_page(self):
        self.client.force_login(self.admin)

        for page_name in PAGES:
            with self.subTest(page_name=page_name):
                response = self.client.get(f'/{page_name}.html')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['admin_capabilities']['can_manage'])
                self.assertTrue(response.context['admin_capabilities']['can_create'])
                self.assertTrue(response.context['admin_capabilities']['can_edit'])
                self.assertTrue(response.context['admin_capabilities']['can_delete'])

    def test_superuser_has_django_create_edit_delete_permissions(self):
        permissions = (
            'auth.view_user',
            'auth.add_user',
            'auth.change_user',
            'auth.delete_user',
        )

        for permission in permissions:
            with self.subTest(permission=permission):
                self.assertTrue(self.admin.has_perm(permission))

    def test_login_rejects_a_non_admin_account(self):
        response = self.client.post(
            reverse('login'),
            {'email': self.regular_user.email, 'password': 'MemberPass123!'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'does not have full administrator access')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_demo_admin_is_repaired_to_full_access(self):
        demo_admin = User.objects.create_user(
            username='admin',
            email='admin@gmail.com',
            password='12345',
            is_staff=False,
            is_superuser=False,
            is_active=False,
        )

        ensure_demo_user()

        demo_admin.refresh_from_db()
        self.assertTrue(demo_admin.is_active)
        self.assertTrue(demo_admin.is_staff)
        self.assertTrue(demo_admin.is_superuser)
