-- Release 1 facility mapping. Rules mirror deploy/facility_rules.json (first matching rule wins).
-- A phone maps to a clinic only if ALL its referrals resolve to exactly one clinic; every other phone
-- (no clinic referral, or several clinics) goes to the holding facility, as approved by the owner.
WITH ref AS (
  SELECT phone, CASE
    WHEN source ~* 'mandebvu\s*pharm' THEN 'mandebvu-pharmacy'
    WHEN source ~* 'mandebvu' THEN 'mandebvu-clinic'
    WHEN source ~* 'n.?g.?ombe' THEN 'ngombe-clinic'
    WHEN source ~* 'chelston' THEN 'chelstone-clinic'
    WHEN source ~* 'avondale' THEN 'avondale-clinic' END AS facility
  FROM public.referrals),
phones AS (SELECT phone FROM public.users UNION SELECT phone FROM public.messages),
clinic AS (SELECT phone, min(facility) AS facility FROM ref WHERE facility IS NOT NULL GROUP BY phone HAVING count(DISTINCT facility)=1),
plan AS (SELECT p.phone, coalesce(c.facility,'unassigned') AS facility,
                CASE WHEN c.facility IS NULL THEN 'holding_facility' ELSE 'referral_rules' END AS method
         FROM phones p LEFT JOIN clinic c USING(phone))
