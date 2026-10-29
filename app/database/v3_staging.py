# Copie dans la base métier les données de l'entrepôt dont le basculement sur le schéma v3 a besoin
# (tables v3_warehouse_*, créées par la migration 0014). À lancer entre « alembic upgrade 0014 » et
# « alembic upgrade head » :
#     python -m app.database.v3_staging
# Lecture seule sur l'entrepôt ; les tables d'attente sont vidées puis remplies (relançable).

from sqlalchemy import text

from app.database.connection import apisolscore_engine, refonte_engine

# n° d'affaire unique dans l'entrepôt (vérifié le 29/10/2026 : 308 787 affaires, aucun doublon).
PROJECTS_SQL = """
    SELECT numero, id::text, nullif(trim(code_service), ''), localisation_fiabilite
    FROM public.affaire
    WHERE numero IS NOT NULL AND trim(numero) <> ''
"""

# Un même nom peut revenir dans une affaire (141 cas le 29/10/2026) : on garde le plus récent.
SURVEYS_SQL = """
    SELECT DISTINCT ON (a.numero, s.nom)
           a.numero,
           s.nom,
           s.localisation_fiabilite,
           coalesce(s.has_mesure_pressiometrique, false),
           coalesce(s.has_essai_penetro_dynamique, false),
           coalesce(s.has_lithologie, false),
           water.sondage_id IS NOT NULL,
           nullif(trim(s.notation), '')
    FROM public.sondage s
    JOIN public.affaire a ON a.id = s.affaire_id
    LEFT JOIN (SELECT DISTINCT sondage_id FROM public.mesure_niveau_eau) water ON water.sondage_id = s.id
    WHERE s.deleted IS NOT TRUE AND s.nom IS NOT NULL AND a.numero IS NOT NULL
    ORDER BY a.numero, s.nom, s.updated_at DESC NULLS LAST
"""

STAGED = {
    "v3_warehouse_projects": (PROJECTS_SQL, "project_number, warehouse_id, business_unit_code, geolocation_reliability"),
    "v3_warehouse_surveys": (
        SURVEYS_SQL,
        "project_number, survey_id, geolocation_reliability, has_pressuremeter, has_penetrometer, has_lithology, "
        "has_water_levels, geological_notation",
    ),
}


def stage() -> dict[str, int]:
    counts = {}

    with apisolscore_engine.connect() as warehouse, refonte_engine.begin() as refonte:
        for table, (query, columns) in STAGED.items():
            rows = warehouse.execute(text(query)).all()
            refonte.execute(text(f"TRUNCATE {table}"))
            # COPY de psycopg : un million de lignes en quelques secondes, là où des INSERT prendraient des minutes.
            with refonte.connection.cursor() as cursor, cursor.copy(f"COPY {table} ({columns}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
            counts[table] = len(rows)

    return counts


if __name__ == "__main__":
    for table, count in stage().items():
        print(f"{table} : {count} lignes")
