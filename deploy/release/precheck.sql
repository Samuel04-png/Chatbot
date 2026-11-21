-- Release 1 pre-check (READ ONLY). Run: supabase db query --linked -f deploy/release/precheck.sql
-- Every value must match the "expected" column in docs/release/RELEASE_1.md before applying.
BEGIN READ ONLY;
SET LOCAL statement_timeout='20s';
SELECT json_build_object(
 'server_version', current_setting('server_version'), 'current_user', current_user,
 'observer_control_exists', EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='observer_control'),
 'rudo_roles', (SELECT coalesce(json_agg(rolname),'[]') FROM pg_roles WHERE rolname IN ('rudo_observer','rudo_observer_audit','rudo_staff_admin')),
 'bot_tables', (SELECT json_agg(relname ORDER BY relname) FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' AND relname IN ('users','messages','referrals','orders','kv','user_state')),
 'public_policies', (SELECT count(*) FROM pg_policies WHERE schemaname='public'),
 'rls_enabled_all', (SELECT bool_and(relrowsecurity) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('users','messages','referrals','orders','kv','user_state')),
 'counts', json_build_object('users',(SELECT count(*) FROM public.users),'messages',(SELECT count(*) FROM public.messages),
   'referrals',(SELECT count(*) FROM public.referrals),'orders',(SELECT count(*) FROM public.orders)),
 'latest_message_at', (SELECT max(created_at) FROM public.messages),
 'acl_fingerprint', md5((SELECT string_agg(relname||coalesce(relacl::text,''),'|' ORDER BY relname) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('users','messages','referrals','orders','kv','user_state')))
);
ROLLBACK;
