-- Release 1 post-check (READ ONLY). Run after apply: supabase db query --linked -f deploy/release/postcheck.sql
BEGIN READ ONLY;
SET LOCAL statement_timeout='20s';
SELECT json_build_object(
 'observer_control_exists', EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='observer_control'),
 'rudo_roles', (SELECT json_agg(json_build_object('r',rolname,'login',rolcanlogin,'bypassrls',rolbypassrls,'super',rolsuper,'createrole',rolcreaterole,'has_password',rolpassword IS NOT NULL) ORDER BY rolname)
               FROM pg_authid WHERE rolname IN ('rudo_observer','rudo_observer_audit','rudo_staff_admin')),
 'public_policies', (SELECT json_agg(tablename||'.'||policyname||' TO '||array_to_string(roles,',') ORDER BY tablename,policyname) FROM pg_policies WHERE schemaname='public'),
 'rls_enabled_all', (SELECT bool_and(relrowsecurity) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('users','messages','referrals','orders','kv','user_state')),
 'acl_fingerprint_unchanged_from_precheck', md5((SELECT string_agg(relname||coalesce(relacl::text,''),'|' ORDER BY relname) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('users','messages','referrals','orders','kv','user_state'))),
 'api_roles_on_observer_control', (SELECT json_object_agg(r,has_schema_privilege(r,'observer_control','USAGE')) FROM unnest(ARRAY['anon','authenticated','service_role']) r),
 'kv_user_state_visible_to_rudo_observer', has_table_privilege('rudo_observer','public.kv','SELECT') OR has_table_privilege('rudo_observer','public.user_state','SELECT'),
 'message_en_visible_to_rudo_observer', has_column_privilege('rudo_observer','public.messages','message_en','SELECT'),
 'address_visible_to_rudo_observer', has_column_privilege('rudo_observer','public.orders','address','SELECT'),
 'staff', (SELECT count(*) FROM observer_control.staff), 'facilities', (SELECT count(*) FROM observer_control.facilities),
 'mapped_phones', (SELECT count(DISTINCT phone) FROM observer_control.source_mappings WHERE approved),
 'counts', json_build_object('users',(SELECT count(*) FROM public.users),'messages',(SELECT count(*) FROM public.messages)),
 'latest_message_at', (SELECT max(created_at) FROM public.messages)
);
ROLLBACK;
