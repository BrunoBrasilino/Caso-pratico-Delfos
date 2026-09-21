-- 1. Geracao total e yield especifico por usina em julho/2026.
select
    sf.solar_field_id,
    sf.name,
    sf.capacity_kwp,
    round(sum(ed.energy_kwh), 1) as total_kwh,
    round(sum(ed.energy_kwh) / sf.capacity_kwp, 2) as specific_yield_kwh_kwp
from solar_field sf
join energy_daily ed
    on ed.solar_field_id = sf.solar_field_id
where ed.date between '2026-07-01' and '2026-07-31'
group by
    sf.solar_field_id,
    sf.name,
    sf.capacity_kwp
order by sf.solar_field_id;

-- 2. Quantidade de dias de julho registrados por usina no banco.
select
    sf.solar_field_id,
    sf.name,
    count(ed.date) as days_registered
from solar_field sf
left join energy_daily ed
    on ed.solar_field_id = sf.solar_field_id
    and ed.date between '2026-07-01' and '2026-07-31'
group by
    sf.solar_field_id,
    sf.name
order by sf.solar_field_id;
