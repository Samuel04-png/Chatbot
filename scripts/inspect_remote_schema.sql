-- Catalog metadata only. No patient rows, function bodies or column defaults.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
SELECT jsonb_build_object(
 'database_version', current_setting('server_version'),
 'tables', (SELECT coalesce(jsonb_agg(jsonb_build_object('schema',n.nspname,'table',c.relname,'kind',c.relkind,'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity) ORDER BY n.nspname,c.relname),'[]') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m')),
 'columns', (SELECT coalesce(jsonb_agg(jsonb_build_object('schema',table_schema,'table',table_name,'column',column_name,'type',data_type,'udt',udt_name,'nullable',is_nullable) ORDER BY table_schema,table_name,ordinal_position),'[]') FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog','information_schema')),
 'constraints', (SELECT coalesce(jsonb_agg(jsonb_build_object('schema',n.nspname,'table',c.relname,'name',k.conname,'type',k.contype,'definition',pg_get_constraintdef(k.oid)) ORDER BY n.nspname,c.relname,k.conname),'[]') FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema')),
 'indexes', (SELECT coalesce(jsonb_agg(jsonb_build_object('schema',schemaname,'table',tablename,'name',indexname,'definition',indexdef) ORDER BY schemaname,tablename,indexname),'[]') FROM pg_indexes WHERE schemaname NOT IN ('pg_catalog','information_schema')),
 'policies', (SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY schemaname,tablename,policyname),'[]') FROM pg_policies p),
 'grants', (SELECT coalesce(jsonb_agg(jsonb_build_object('schema',table_schema,'table',table_name,'grantee',grantee,'privilege',privilege_type) ORDER BY table_schema,table_name,grantee,privilege_type),'[]') FROM information_schema.role_table_grants WHERE table_schema NOT IN ('pg_catalog','information_schema')),
 'functions', (SELECT coalesce(jsonb_agg(jsonb_build_object('schema',n.nspname,'name',p.proname,'arguments',pg_get_function_identity_arguments(p.oid),'security_definer',p.prosecdef) ORDER BY n.nspname,p.proname),'[]') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema'))
) AS schema_inventory;
ROLLBACK;
