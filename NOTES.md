# Journal des tournages — ce qu'on observe, sans y toucher tout de suite

Ce fichier ne décrit pas le code : il note ce qu'un rendu a donné en vrai, épisode par
épisode. Un défaut vu une fois est une anecdote, vu trois fois c'est un correctif à faire.
Rien n'est modifié sur la foi d'une seule occurrence.

## 2026-08-24 — screencast Goose (`2026-08-24_17-27-43_montage`)

Cerveau : `openrouter/anthropic/claude-sonnet-5`, variant `medium`, via opencode.
Verdict d'ensemble d'Alex : **ça a bien marché**. Deux réserves.

### 1. Le son de l'intro

Enchaînement entendu : **a capella, puis un blanc, puis un tout petit peu de musique,
coupée net**. Ce n'est pas une décision du modèle — l'EDL ne porte que les coupes et les
plans. C'est le carton d'intro : la piste chantée, le silence entre les deux, et la
musique de `sonorita` qui rentre trop tard puis se fait trancher par la fin du carton.
À regarder du côté du montage du bookend (durée du carton, offset et fondu de la musique,
alignement du jingle), pas du côté du modèle.

### 2. La fin de l'installation a été coupée

Ça, en revanche, c'est bien une décision du cerveau : un `drop` sur la fin d'un passage
qu'Alex voulait garder. Deux causes possibles, à départager avant de conclure :

- **le modèle** — il a jugé la fin de séquence sans intérêt ;
- **le prompt** — `montage.md` autorise `fumble` à couvrir « des dizaines de secondes »
  quand le locuteur patauge, et demande de couper les fins de phrase abandonnées. Une
  installation qui se termine dans un moment d'hésitation coche les deux cases.

Si le défaut se reproduit avec un autre modèle, c'est le prompt qu'il faut reprendre, pas
le modèle. La trace de l'appel (`brain-log/`) garde le `reason` retenu pour ce span : c'est
lui qui tranchera.
