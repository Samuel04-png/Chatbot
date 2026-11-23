-- Firebase migration post-check (READ ONLY). Compare counts and acl_fingerprint with the pre-check.
BEGIN READ ONLY;
SET LOCAL statement_timeout='20s';
SELECT json_build_object(
 'schemas', (SELECT json_agg(nspname ORDER BY nspname) FROM pg_namespace WHERE nspname IN ('firebase_migration','firebase_import')),
 'tables_rls', (SELECT json_object_agg(n.nspname||'.'||c.relname, c.relrowsecurity ORDER BY 1) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname IN ('firebase_migration','firebase_import') AND c.relkind='r'),
 'migrator_role', (SELECT json_build_object('login',rolcanlogin,'super',rolsuper,'bypassrls',rolbypassrls,'createrole',rolcreaterole)
                   FROM pg_roles WHERE rolname='rudo_migrator'),
 'public_api_roles_with_access', (SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema IN ('firebase_migration','firebase_import')
                   AND grantee IN ('anon','authenticated','service_role','PUBLIC')),
 'public_api_schema_usage', (SELECT count(*) FROM unnest(ARRAY['anon','authenticated','service_role']) r, unnest(ARRAY['firebase_migration','firebase_import']) s
                   WHERE has_schema_privilege(r,s,'USAGE')),
 'migrator_can_read_patients', has_table_privilege('rudo_migrator','public.users','SELECT'),
 'migrator_can_read_auth_users', has_table_privilege('rudo_migrator','auth.users','SELECT'),
 'owner_app_column', EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='firebase_migration' AND table_name='accounts' AND column_name='owner_app'),
 'ledger_rows', (SELECT count(*) FROM firebase_migration.accounts), 'documents', (SELECT count(*) FROM firebase_import.documents),
 'auth_users', (SELECT count(*) FROM auth.users), 'staff', (SELECT count(*) FROM observer_control.staff),
 'counts', json_build_object('users',(SELECT count(*) FROM public.users),'messages',(SELECT count(*) FROM public.messages),
   'referrals',(SELECT count(*) FROM public.referrals),'orders',(SELECT count(*) FROM public.orders)),
 'acl_fingerprint', md5((SELECT string_agg(relname||coalesce(relacl::text,''),'|' ORDER BY relname) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('users','messages','referrals','orders','kv','user_state'))),
 'public_policies', (SELECT count(*) FROM pg_policies WHERE schemaname='public')
) AS c;
ROLLBACK;
