Place Supabase's database CA certificate here as `prod-supabase.crt` (Supabase Dashboard → Project Settings →
Database → SSL Configuration → Download certificate). It is a public CA certificate, not a secret. The image
copies this folder so database DSNs can use `sslmode=verify-full&sslrootcert=/app/deploy/certs/prod-supabase.crt`.
