# Génère sondages.xls, le classeur au format .xls (Excel 97-2003) lu par test_routes.py.
# xlwt n'est pas une dépendance du projet : on le lance une fois dans un conteneur jetable,
# depuis la racine de back-fastapi :
#   docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/tests/domains/survey_imports/fixtures:/out" \
#     python:3.13-slim sh -c "pip install -q xlwt && python /out/make_sondages_xls.py"
# La dernière cellule de RG1 est une formule en erreur (1/0) sans valeur calculée : elle doit être lue vide.

from datetime import date, datetime
import xlwt

book = xlwt.Workbook(encoding="utf-8")
day = xlwt.easyxf(num_format_str="DD/MM/YYYY")
moment = xlwt.easyxf(num_format_str="DD/MM/YYYY HH:MM")
sheet = book.add_sheet("Sondages")
for column, title in enumerate(["Nom", "Début", "Latitude", "Longitude", "Élévation", "Niveau d'eau", "Validé"]):
    sheet.write(0, column, title)
sheet.write(1, 0, "SP1"); sheet.write(1, 1, date(2020, 1, 24), day); sheet.write(1, 2, 47.443257021); sheet.write(1, 3, -0.543013886); sheet.write(1, 4, 31.92); sheet.write(1, 6, True)
sheet.write(2, 0, "RG1"); sheet.write(2, 1, datetime(2020, 1, 27, 9, 30), moment); sheet.write(2, 2, 47.443482615); sheet.write(2, 3, -0.542854434); sheet.write(2, 4, 32); sheet.write(2, 5, 0.00001); sheet.write(2, 6, xlwt.Formula("1/0"))
projet = book.add_sheet("Projet")
projet.write(0, 0, "Référence"); projet.write(0, 1, "PR.GFIT.26.0004")
book.save("/out/sondages.xls")
