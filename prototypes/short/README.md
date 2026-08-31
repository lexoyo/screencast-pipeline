# Banc d'essai des shorts — à intégrer, pas à utiliser tel quel

Le code qui a servi à fabriquer les trois premiers shorts, le 31/08/2026. Il est **hors du
pipeline** : aucune étape ne l'appelle, `./screencast` l'ignore. Il est versionné ici pour
que le travail ne reparte pas de zéro quand l'étape `short` sera écrite — la spec est dans
`NOTES.md`, section « L'étape `short` reste à écrire ».

| Fichier | Ce qu'il fait | Ce qu'il faut en garder |
|---|---|---|
| `activity.py` | zone d'activité par différence d'images | **la méthode est le mauvais signal** : elle suit ce qui bouge, pas ce dont la voix parle. À remplacer par le suivi du curseur |
| `short.py` | composition verticale, cadrage par paliers, accélération, sous-titres | la structure est bonne : bornes sur cues, ×1,15, cadre calé en haut, webcam exclue |
| `run3.py` | les trois shorts de cet épisode, cadrages forcés à la main | les cadrages sont **codés en dur** — c'est ce qu'il faut supprimer en automatisant |
| `short3.py` | composition à deux vignettes | à reprendre : certains passages ont leur sujet aux deux bouts de l'écran |

Chemins codés en dur vers le rush et l'épisode du 31/08 : ce sont des prototypes, pas des
outils.
