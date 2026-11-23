-- Firebase migration pre-check (READ ONLY). Run: supabase db query --linked -f deploy/release/firebase_precheck.sql
BEGIN READ ONLY;
SET LOCAL statement_timeout='20s';
SELECT json_build_object(
 'current_user', current_user,
 'release1_present', EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='observer_control'),
 'firebase_migration_absent', NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='firebase_migration'),
 'firebase_import_absent', NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='firebase_import'),
 'rudo_migrator_absent', NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_migrator'),
 'auth_users', (SELECT count(*) FROM auth.users),
 'auth_identities', (SELECT count(*) FROM auth.identities),
 'staff', (SELECT count(*) FROM observer_control.staff),
 'counts', json_build_object('users',(SELECT count(*) FROM public.users),'messages',(SELECT count(*) FROM public.messages),
   'referrals',(SELECT count(*) FROM public.referrals),'orders',(SELECT count(*) FROM public.orders)),
 'acl_fingerprint', md5((SELECT string_agg(relname||coalesce(relacl::text,''),'|' ORDER BY relname) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('users','messages','referrals','orders','kv','user_state'))),
 'public_policies', (SELECT count(*) FROM pg_policies WHERE schemaname='public')
) AS c;
ROLLBACK;
