// =====================================================================
// Gabarit « Références projets » Camptocamp — document unique multi-projets
//
// PARTI PRIS GRAPHIQUE : la grille modulaire en aplats francs, jouee sur des
// mesures variables. La fiche se lit en blocs pleins poses sur du blanc —
// jamais en filets, jamais en cadres. C'est la declinaison directe de l'ADN
// pixel-art de la marque (angles droits, aplats, geometrie stricte) :
//   · numero de projet en gros chiffre orange — ancrage a surface minime
//   · faits du projet en cellules modulaires juxtaposees (aucun filet)
//   · contacts et lien du projet publie sur une seconde rangee de ces
//     memes cellules — les seules donnees cliquables de la fiche
//   · technologies et equipe en rangees de modules qui se replient
//   · chapitres sans numerotation : le libelle seul porte l'entete
//   · teinte peche reservee aux chapitres identite (environnement, resultats)
//   · la couverture EST l'index : plus de page de sommaire separee
//
// RYTHME DE COMPOSITION : chaque chapitre porte un `layout` et une teinte
// decides en amont par app/reference_renderer.py (fonction dediee au PDF,
// _reshape_chapitres_pdf) — le gabarit ne fait que rendre. Cinq layouts :
// texte seul pleine largeur (teinte ou non), deux colonnes (texte tres long
// sans visuel), mise en regard d'un visuel (alternee d'un chapitre a
// l'autre), pile titre/texte/visuel (reservee a l'identite du chapitre
// environnement), et l'image "libre" hors chapitre (au plus une, a la place
// du premier chapitre-image manquant, cf. image-libre).
//
// Charte respectee : fond blanc exclusif, orange en accent (< 30 %),
// angles droits, zero ombre, zero degrade, Messina Sans, sentence case.
// En-tete / pied / typographie : codes du gabarit corporate Camptocamp.
//
// DESTINATION : client / appel d'offre — aucune mention de confidentialite.
// Donnees : YAML passe via sys.inputs.data (cf. app/reference_renderer.py).
// =====================================================================

// --- Jetons de marque -----------------------------------------------
#let c2c-orange = rgb("#FF680A")
#let c2c-grey   = rgb("#7A7F82")
#let c2c-ink    = rgb("#1A1A1A")
#let c2c-tint   = rgb("#F4F4F4")
#let c2c-peach  = rgb("#FDF0E9")  // teinte réservée aux chapitres environnement / resultats
#let c2c-font   = "Messina Sans"

#let logo-wordmark = "assets/c2c-wordmark.png"
// Icone montagne EN VECTEUR (SVG) et non en raster : la version PNG
// (2500x2247) reduite a 18.75pt (~25px a l'ecran) prenait un halo gris-brun
// sur ses aretes en escalier — le "glitch gris" signale. Cf. l'en-tete de
// assets/c2c-icon.svg.
#let logo-icon     = "assets/c2c-icon.svg"

// --- Donnees ------------------------------------------------------------
// Chargees avant la geometrie de page : marge-x en depend desormais (levier
// de la boucle de remplissage, cf. plus bas) — Typst capture les variables
// par portee lexicale a la DEFINITION d'une fonction, pas a son appel, donc
// `doc` doit exister avant tout ce qui le lit, y compris les constantes de
// geometrie.
#let data-path = sys.inputs.at("data", default: "data/references-exemple.yaml")
#let doc = yaml(data-path)
#let projets = doc.at("projets", default: ())

#let titre        = doc.at("titre", default: "Références projets")
#let sous-titre   = doc.at("sous_titre", default: "Camptocamp SA")
#let sur-titre    = doc.at("sur_titre", default: "")
#let label-entete = doc.at("label_entete", default: "Références projets")
#let doc-name     = doc.at("document_name", default: "Références projets")
#let annee        = doc.at("annee", default: "")

// --- Assemblage d'un document multi-projets ----------------------------
// Un lot de references n'est PAS compile d'un seul tenant : chaque projet est
// compose seul, avec ses propres leviers de remplissage, puis les PDF sont
// assembles (cf. reference_renderer.render_pdf). C'est la seule façon de
// garantir qu'un projet rende exactement pareil seul et en lot — des leviers
// communs a tout le document faisaient payer a chaque projet la densite du
// plus charge, jusqu'a supprimer les visuels de cloture de tous (bug signale).
//
// Deux consequences ici, et deux seulement — la mise en page d'un projet, elle,
// est rigoureusement la meme dans les deux cas :
//   · `page_offset` — numero de la premiere page de ce fragment, moins un ;
//   · `page_total`  — nombre de pages du document ASSEMBLE. A zero (compilation
//     autonome), la pagination retombe sur le compte du fragment lui-meme.
#let page-offset = doc.at("page_offset", default: 0)
#let page-total  = doc.at("page_total", default: 0)

// Index de la couverture : une entree par projet du lot, {titre, page}. Rendu
// seulement s'il est fourni — la couverture est un fragment a part, compile
// sans aucun projet (cf. plus bas).
#let index = doc.at("index", default: ())

// --- Leviers de remplissage --------------------------------------------
// Decides par app/reference_renderer.py (boucle de verification du
// remplissage des pages) : jamais choisis au hasard dans le gabarit, qui ne
// fait qu'appliquer la valeur reçue.
// Contrainte 1 — "Environnement" tient sur une seule page (la page 1 quand
// l'equipe n'est pas renseignee) :
//   · corps-size      — taille du corps de texte des chapitres (pt) ;
//   · padding-chapeau — marges internes de l'aplat "Contexte complet" ;
//   · gap-titre       — blanc entre le bloc de titre et les elements cles ;
//   · marge-env-bas   — blanc entre "Environnement" et le pied de page ;
//   · image-libre-echelle       — rognage de l'image "libre" (vitrine),
//     PLAFONNE a 30 %, puis 40 % au palier le plus dense ;
//   · plancher-visuel-empile    — rognage du visuel "Environnement" lui-meme,
//     PLAFONNE a 20 %, puis 30 % au palier le plus dense ;
//   · environnement-full-pied   — colle "Environnement" au bord bas REEL de
//     la page (recouvre le pied de page normal, supprime sur cette page) ;
//   · masquer-image-libre       — dernier repli : l'image "libre" disparait.
// Contrainte 2 — le document tient en 2 pages au plus, en n'agissant que sur
// ce qui SUIT "Environnement" :
//   · echelle-gap-chapitres — facteur sur le blanc entre deux chapitres ;
//   · marge-resultats       — marges internes de l'aplat de cloture ;
//   · sans-image-resultats  — abandon du visuel du chapitre de cloture.
// La sequence exacte (quel levier, dans quel ordre, jusqu'ou) est decidee cote
// Python et nulle part ailleurs : cf. render_pdf._converger_un_passage.
//
// `echelle-duo` et `marge-x` restent lus (le gabarit s'en sert) mais ne sont
// pas des leviers : la sequence de repli ci-dessus ne les mentionne pas.
#let echelle-duo  = doc.at("echelle_duo", default: 1.0)
#let corps-size   = doc.at("corps_size", default: 9) * 1pt
// Facteur sur le blanc entre deux chapitres (cf. gap-chapitre plus bas).
#let echelle-gap-chapitres = doc.at("echelle_gap_chapitres", default: 1.0)
// Abandon du visuel du chapitre de cloture — tout dernier repli de la
// contrainte "2 pages" (cf. chapitre()).
#let sans-image-resultats = doc.at("sans_image_resultats", default: false)
// Blanc entre le bas du chapitre "Environnement" (ancre en bas de page, cf.
// m-stack) et la mention (c) + pagination. Sans effet en mode "full pied"
// (environnement-full-pied) : cf. pad-bas-ancrage plus bas.
#let marge-env-bas = doc.at("marge_env_bas", default: 60) * 1pt
// Facteur applique a la HAUTEUR CIBLE de l'image vitrine (cf.
// ratio-image-libre plus bas) : 1.0 = format nominal 911x370, aucun rognage
// au-dela du recadrage de format. LEVIER de la sequence de repli
// d'"Environnement" (cf. le lexique ci-dessus) : reduire ce facteur revele
// moins du fichier a hauteur constante, donc le rogne — PLAFONNE a 30 % de
// rognage, puis 40 % au palier le plus dense (cf. IMAGE_LIBRE_CROP_LADDER
// cote Python).
#let image-libre-echelle = doc.at("image_libre_echelle", default: 1.0)

// Marge interne haute de l'aplat de cloture (resultats) et blanc entre son
// contenu et son pied de page embarque — les deux sont egaux, ils servent a
// CENTRER le contenu du chapitre dans son aplat (demande explicite). Levier
// de la boucle de remplissage : reduits d'abord si les autres chapitres sont
// plus denses (cf. MARGE_RESULTATS_LADDER cote Python). Le pied de page, lui,
// ne bouge pas : il reste cale par l'inset BAS de l'aplat (18pt, inchange).
#let marge-resultats = doc.at("marge_resultats", default: 40) * 1pt

// Blanc entre le bloc de titre de la fiche (numero + client + designation) et
// la rangee d'elements cles. Au nominal il vaut marge-haut-page : le blanc
// SOUS le bloc de titre est alors exactement egal a celui qui le separe du
// haut du document (demande explicite). Les deux valeurs doivent donc rester
// egales — cf. GAP_TITRE_LADDER cote Python, ou le palier nominal est pose.
// Levier de la boucle de verification, comme marge-resultats.
#let gap-titre = doc.at("gap_titre", default: 45) * 1pt

// --- Geometrie de page ----------------------------------------------
#let page-w  = 595.28pt        // A4
#let page-h  = 841.89pt        // A4
#let marge-x = doc.at("marge_x", default: 56.7) * 1pt
// Gap standard entre deux elements verticalement adjacents (image libre ->
// chapitre suivant, dernier chapitre -> pied de page, cf. plus bas) — UNE
// seule valeur nommee, pour que ces deux espaces restent toujours identiques
// (demande explicite) plutot que deux litteraux qui peuvent diverger.
#let gap-standard = 22pt * 2 / 3
// Blanc entre deux chapitres successifs (l'espace "above" de leur aplat).
// 22pt au nominal ; la boucle de remplissage le reduit par paliers de 10 %
// pour tenir la contrainte "2 pages" (cf. GAP_CHAPITRES_LADDER cote Python).
#let gap-chapitre = 22pt * echelle-gap-chapitres
// Marge basse des pages interieures (cf. #set page plus bas) — dupliquee ici
// en constante nommee : m-stack en a besoin pour calculer la place restante
// sur la page courante avant de choisir un variant d'image (cf. m-stack).
// La faire egale a gap-standard (essaye) faisait deborder le texte du pied
// de page hors de la page physique : footer-descent (71% fixe) positionnait
// le texte trop bas pour une bande aussi petite. La bande reste donc a sa
// taille sure (85pt/2) ; c'est footer-descent, plus bas, qui est recalcule
// pour que le blanc AU-DESSUS du pied de page (pas la bande entiere) egale
// gap-standard — meme resultat visuel demande, sans risque de debordement.
#let marge-bas-page = 85pt / 2
// Marge haute des pages interieures (cf. #set page plus bas) — meme raison :
// m-stack en a besoin pour calculer la hauteur disponible sur une page fraiche.
// C'est aussi la valeur nominale de gap-titre (cf. sa note) : le bloc de titre
// doit avoir le meme blanc au-dessus et en dessous.
#let marge-haut-page = 45pt
#let texte-w = page-w - 2 * marge-x
#let gouttiere = 22pt
#let demi = (texte-w - gouttiere) / 2
// Mesure de texte fixe des motifs duo (55 % de texte-w) — jamais relative au
// conteneur : un aplat debordant (resultats) ne doit pas elargir la colonne de
// texte, seul le visuel doit profiter de la largeur liberee a droite.
#let duo-texte-w = texte-w * 1.12 / 2
// Colonne de texte pour "resultats" (seul chapitre bleed, cf. m-duo) :
// derivee pour que largeur-image-duo(bleed:true, ..) tombe EXACTEMENT sur
// texte-w/2 (demande explicite : "l'image occupe 50% du bloc"), quelle que
// soit la valeur de texte-w (marge-x variable via la boucle de remplissage).
#let duo-texte-w-resultats = texte-w / 2 - gouttiere

// --- Reglages generaux ------------------------------------------------
#set document(
  title: titre + " — " + sous-titre,
  author: doc.at("author", default: "Camptocamp SA"),
)
#set text(font: c2c-font, size: 10pt, fill: c2c-ink, lang: "fr")
#set par(justify: true, leading: 0.62em, spacing: 1.1em)
#set list(
  indent: 10pt,
  body-indent: 6pt,
  marker: (
    [#text(fill: c2c-orange)[➔]],
    [#text(fill: c2c-orange)[■]],
  ),
)

#show link: it => text(fill: c2c-ink)[#it]
#show strong: it => text(font: c2c-font, weight: "bold")[#it.body]
#show emph: it => text(font: c2c-font, style: "italic")[#it.body]

// Les titres de niveau 1 ne servent qu'a alimenter l'index et les signets :
// la composition du titre de projet est posee a la main, juste apres.
#set heading(numbering: (..n) => {
  let i = n.pos().first()
  if i < 10 { "0" + str(i) } else { str(i) }
})
#show heading.where(level: 1): it => none

// En-tete courant : sobre, à la Fiche projet — la premiere page d'un projet ne
// porte RIEN dans l'entete (l'icone y vivait seule, mais desalignee de la
// ligne de titre du corps ; deplacee dans le bloc d'identite lui-meme —
// cf. la grille numero/client/icone — pour etre reellement sur la meme ligne
// que le titre, mesure sur le rendu), les pages suivantes rappellent le
// projet en toutes lettres et portent le logotype complet.
// `apres` designe le titre de CETTE page quand elle en ouvre une (le heading,
// pose en tete de corps de page, se situe apres l'entete dans l'ordre du
// document) ; sans heading a venir sur la page courante, c'est une suite.
#let running-header = context {
  let ici = here()
  let apres = query(selector(heading.where(level: 1)).after(ici))
  let avant = query(selector(heading.where(level: 1)).before(ici))
  let premiere-page = apres.len() > 0 and apres.first().location().page() == ici.page()
  if premiere-page {
    none
  } else {
    let courant = if avant.len() > 0 { avant.last().body } else { [#label-entete] }
    grid(
      columns: (1fr, auto),
      align: (left + horizon, right + horizon),
      text(size: 9.5pt, fill: c2c-grey, weight: "semibold")[#courant],
      box(width: 18.75pt, height: 17.25pt)[#image(logo-icon, width: 18.75pt)],
    )
  }
}

// Un visuel pleine largeur ancre en bas de page (visuel empile debordant)
// prend la place habituelle du pied de page — le pied
// normal doit alors s'effacer sur CETTE page. Resultats fait l'inverse : son
// encart de cloture porte son propre pied (cf. ligne-pied) et supprime aussi
// le pied normal, pour ne pas le dupliquer.
// Poids du ressort d'ancrage du chapitre de cloture (cf. chapitre()), face au
// 1fr d'"Environnement" (cf. m-stack, `ancre-bas`). Deux ressorts de meme
// poids sur une meme page se partagent le blanc a parts EGALES : sur une fiche
// assez courte pour tenir sur une page, la cloture se retrouvait alors au
// milieu du bas de page au lieu de son bord, et un blanc s'ouvrait sous
// "Environnement" — la ou il doit rester au-DESSUS de lui (demande explicite).
// Un poids negligeable regle les deux cas d'un coup :
//   · cloture seule sur sa page — c'est le seul ressort, il prend tout le
//     blanc restant, donc l'encart descend bien jusqu'au bord ;
//   · cloture sur la meme page qu'"Environnement" — le 1fr de celui-ci prend
//     tout, remplit la page jusqu'a l'encart, qui se retrouve donc AUSSI
//     colle au bord, sans blanc entre les deux.
#let poids-ressort-cloture = 0.001

// Pagination « n / total » — un seul endroit pour les trois pieds de page qui
// l'affichent (pied courant, pied embarque de la cloture, bande de pied d'un
// visuel debordant). `page-total` prime quand il est fourni : le compte propre
// au fragment ne vaut rien une fois le document assemble.
#let pagination() = context {
  let total = if page-total > 0 { page-total } else { counter(page).final().first() }
  text(size: 8pt, fill: c2c-orange, weight: "black")[#counter(page).display() / #total]
}

#let PIED-SUPPRIME = <pied-supprime>
#let supprimer-pied() = [#metadata(none) <pied-supprime>]

#let running-footer = context {
  let ici = here()
  let supprime = query(PIED-SUPPRIME).any(m => m.location().page() == ici.page())
  if not supprime {
    text(size: 8pt, fill: c2c-orange, weight: "semibold")[© Camptocamp | #annee | #doc-name]
    h(1fr)
    pagination()
  }
}

// Tout visuel pleine largeur ancre en bas de page (visuel empile debordant,
// encart de cloture de resultats) utilise `place(bottom,
// float: true)` : seul mecanisme fiable trouve a l'usage. Deux alternatives
// testees et abandonnees :
//   · `v()` calcule + bloc normal — le flux ne peut de toute façon jamais
//     deborder la marge de pied habituelle, quel que soit l'espacement
//     insere avant ; impossible d'atteindre ainsi le bord reel de la page.
//   · mesure (`measure()`) + `place(dy: ...)` calcule a la main — fonctionne
//     isolement, mais repete plusieurs fois dans un meme document, la
//     resolution de mise en page se derobe plus loin : du contenu (la
//     section Resultats) disparaissait purement et simplement, de façon
//     reproductible mais sans cause identifiee avec certitude. Le risque de
//     perdre du contenu silencieusement l'emporte sur le gain de compacite.
// `float: true` reserve correctement sa place dans le flux (le chapitre
// suivant ne peut pas chevaucher) et ne recree pas cette instabilite.
// `place(bottom)` cale le bord bas du contenu sur la marge de pied habituelle
// (page_h - marge basse) : sans decalage, un espace blanc de la hauteur de
// cette marge subsiste sous le contenu. `dy: dy-pied-reel` (= la marge basse
// elle-meme) annule exactement cet espace, pour que le bloc/visuel touche
// reellement le bord bas physique de la page — aucune marge residuelle
// (mesure sur le rendu : bug signale, corrige).
// TOUJOURS egal a marge-bas-page (jamais un litteral duplique) : un 85pt fige
// ici pendant que marge-bas-page changeait ailleurs a deja produit un
// decalage errone qui poussait le bas du bloc "resultats" hors de la page
// (bug signale, corrige).
#let dy-pied-reel = marge-bas-page

// Pied de page rejoue a l'identique, pour l'encart de resultats qui l'englobe
// (cf. m-* / bloc-plein, parametre `pied`). Resultats n'est plus un aplat
// debordant (cf. reference_renderer.py — plus de chapitre confie a des marges
// asymetriques) : l'aplat confine reserve deja marge-x des deux cotes, ce
// pied n'a donc besoin d'aucun inset dedie.
// `above: marge-resultats` (et non 14pt fige) : c'est la marge BASSE du
// contenu du chapitre de cloture, symetrique de sa marge haute (l'inset
// superieur de bloc-plein en mode bleed) — les deux centrent le contenu dans
// l'aplat. Le pied lui-meme ne se deplace pas pour autant : sa position est
// fixee par l'inset BAS de l'aplat, pas par cet espace, qui ne fait que
// repousser le CONTENU vers le haut.
#let ligne-pied() = block(above: marge-resultats, below: 0pt, width: 100%)[
  #grid(
    columns: (1fr, auto),
    text(size: 8pt, fill: c2c-orange, weight: "semibold")[© Camptocamp | #annee | #doc-name],
    pagination(),
  )
]

// =====================================================================
// COMPOSANTS MODULAIRES
// =====================================================================

// Marge interne d'un aplat confine (chapitre, chapeau) — la mesure de
// reference de tout le document.
#let padding-aplat = 16pt
// Le chapeau ("Contexte complet du projet") est le SEUL aplat a s'en ecarter :
// +30 % au nominal (demande explicite). Il n'a plus le meme role que les
// chapitres depuis qu'un visuel court derriere lui — cette respiration
// supplementaire lui donne l'assise d'un cartouche pose sur l'image, la ou un
// chapitre n'est pose que sur du blanc. Levier de la contrainte 1, d'ou la
// valeur reçue plutot que calculee (cf. PADDING_CHAPEAU_LADDER cote Python).
#let padding-chapeau = doc.at("padding_chapeau", default: 20.8) * 1pt

// Espace entre deux cellules modulaires voisines (cellules de faits, tuiles de
// competences). Constante nommee : le bloc "Contexte complet du projet" se
// pose desormais a cette MEME distance sous la rangee de faits — il doit se
// lire comme un element de plus de la meme grille, pas comme un chapitre
// detache (demande explicite, maquette fournie).
#let gap-cellules = 3pt

// Blanc AUTOUR de la rangee de qualification (competences / equipe) — au-dessus
// comme en dessous. Volontairement bien plus large que gap-cellules : cette
// rangee n'est pas une cellule de faits de plus, elle porte son propre motif
// (micro-entete + modules), et doit se detacher des deux rangees de cellules
// qui la precedent comme du chapeau qui la suit.
//
// CE N'EST PAS UN LEVIER DE LA BOUCLE, et c'est le point : ce blanc-la ne se
// negocie pas. Quand la fiche doit gagner de la place, la boucle a tous ses
// autres crans (corps de texte, padding du chapeau, blancs du titre, blancs
// entre chapitres, marges de la cloture, rognage des visuels) — demande
// explicite : « augmenter l'espacement autour de ce bloc [...] et ne pas y
// toucher dans la boucle ; dans ce cas toucher aux autres parametres comme
// l'impose la boucle ». D'ou une valeur en dur, et non un `doc.at(..)`.
//
// gap-standard : la mesure de blanc de reference du document (celle qui separe
// deja l'image libre du chapitre suivant, et le dernier chapitre du pied de
// page) plutot qu'un litteral de plus.
#let gap-qualification = gap-standard

// Cellules de faits juxtaposees — remplace la table a filets du gabarit
// corporate : meme information, lecture en blocs.
// Le fond est porte par `grid.cell` et non par un `block` : la cellule occupe
// alors exactement la hauteur de sa rangee, et toutes les cellules d'une meme
// rangee s'alignent — un `block(height: 100%)` s'etirerait sur la page entiere.
// Une cellule, extraite de `faits` : la rangee des contacts et du lien de
// publication est faite des MEMES cellules (meme aplat, meme micro-libelle,
// meme corps) — c'est ce qui la rattache visuellement a la grille des faits
// plutot que d'en faire un bloc de plus. Deux definitions jumelles auraient
// diverge au premier reglage de padding.
#let cellule-fait(label, corps) = grid.cell(fill: c2c-tint, inset: (x: 9pt, y: 7pt))[
  #set par(justify: false, leading: 0.5em)
  #stack(
    dir: ttb,
    spacing: 4pt,
    text(size: 6.5pt, fill: c2c-grey, weight: "bold", tracking: 0.6pt)[#upper(label)],
    corps,
  )
]

#let faits(cells) = grid(
  columns: cells.map(_ => 1fr),
  column-gutter: gap-cellules,
  ..cells.map(c => cellule-fait(c.at(0), text(size: 9.5pt, weight: "semibold")[#c.at(1)])),
)

// Espace de largeur nulle — seul point de coupure qu'on puisse offrir a une
// URL, qui n'a ni espace ni trait d'union ou Typst pourrait la replier.
// Compose par code de caractere plutot qu'ecrit en clair : un caractere
// invisible dans le source est introuvable a la relecture.
#let zwsp = str.from-unicode(0x200B)

// Corps de la cellule "Contacts" — une ligne par point de contact (trois au
// plus, cf. reference_renderer.MAX_CONTACTS), nom en demi-gras puis adresse a
// la suite, separes du meme point median gris que le role d'un membre
// d'equipe (cf. modules-equipe) : la fiche n'a qu'une seule façon d'accoler
// un nom et sa qualification.
//
// L'adresse est un `link("mailto:...")`, donc une annotation cliquable dans
// le PDF, et elle est ORANGE : c'est le seul signal dont dispose le lecteur
// pour savoir qu'il peut cliquer (la regle `show link` du document ramene
// autrement tout lien a la couleur du texte courant — voulu pour un lien
// noye dans un paragraphe, contre-productif ici). La couleur est posee DANS
// le corps du lien, jamais autour : un `text(fill: ...)` enveloppant serait
// ecrase par cette meme regle.
//
// TOUT le contact est a 8.5pt, nom compris — contrairement aux autres
// cellules de faits, dont la valeur est a 9.5pt. Un contact n'est pas une
// valeur courte comme un secteur ou une periode : c'est un nom ET une adresse
// sur une meme ligne, et 9.5pt pour le nom suffisait a faire passer
// « Philippe Lasserre · philippe.lasserre@caissedesdepots.fr » sur deux
// lignes dans une cellule de demi-mesure (bug signale). Une seule taille pour
// les deux, c'est aussi une hauteur de cellule previsible : une ligne par
// contact.
// Une ligne de contact : nom en demi-gras, puis adresse a la suite, separes du
// meme point median gris que le role d'un membre d'equipe (cf.
// modules-equipe) — la fiche n'a qu'une seule façon d'accoler un nom et sa
// qualification.
//
// Fonction a part, et pas seulement une branche de `corps-contacts` : c'est
// exactement ce contenu que la rangee MESURE pour decider de la largeur de sa
// premiere colonne (cf. son usage dans le corps de la fiche). Deux
// constructions differentes pour le rendu et pour la mesure auraient fini par
// se contredire, et la cellule serait retombee a une largeur fausse.
#let ligne-contact(c) = {
  let nom = c.at("nom", default: "")
  let mail = c.at("email", default: "")
  let adresse = if mail != "" {
    link("mailto:" + mail)[#text(size: 8.5pt, fill: c2c-orange, weight: "semibold")[#mail.replace("@", "@" + zwsp)]]
  }
  if nom != "" and mail != "" {
    [#text(size: 8.5pt, weight: "semibold")[#nom]#text(size: 8.5pt, fill: c2c-grey)[ · ]#adresse]
  } else if mail != "" {
    adresse
  } else {
    text(size: 8.5pt, weight: "semibold")[#nom]
  }
}

#let corps-contacts(contacts) = {
  set par(justify: false, leading: 0.5em)
  stack(dir: ttb, spacing: 4pt, ..contacts.map(ligne-contact))
}

// Largeur de la cellule "Contacts" quand la rangee porte AUSSI le lien.
//
// Ni une demi-mesure figee, ni la place que le contact demande sans limite :
//   · PLANCHER — la demi-mesure. La rangee garde donc son allure de deux
//     cellules egales dans le cas courant, elle ne s'elargit que si un
//     contact en a reellement besoin.
//   · la largeur DEMANDEE par le contact le plus long, insets compris. Une
//     demi-cellule offre 221.4pt de contenu, et « Philippe Lasserre ·
//     philippe.lasserre@caissedesdepots.fr » en reclame 224 : 2.6pt de trop,
//     et le contact passait sur deux lignes (bug signale). Reduire encore le
//     corps de texte pour 2.6pt aurait rendu la rangee plus petite que tout
//     le reste de la fiche ; c'est la colonne qui cede.
//   · PLAFOND — les deux tiers de la mesure de texte, pour que le lien garde
//     toujours un tiers de la rangee. Un contact plus long que ça se replie,
//     et c'est la bonne issue : mieux vaut deux lignes de contact qu'un lien
//     illisible.
#let largeur-contacts(contacts) = {
  let demande = calc.max(..contacts.map(c => measure(ligne-contact(c)).width)) + 2 * 9pt
  calc.max(demi, calc.min(demande, texte-w * 2 / 3))
}

// Corps de la cellule "Projet publie" — l'URL entiere est la CIBLE du lien,
// le libelle affiche est deja debarrasse de son schema cote Python (cf.
// reference_renderer._lien_label) : le gabarit ne recompose rien.
// Les separateurs d'URL reçoivent un zwsp pour que l'adresse puisse se
// replier dans la cellule au lieu d'en deborder — invisible a la lecture,
// et absent de la cible.
#let coupures-url(label) = {
  let out = label
  for sep in ("/", "?", "&", "=", "_", ".") {
    out = out.replace(sep, sep + zwsp)
  }
  out
}

#let corps-lien(url, label) = {
  set par(justify: false, leading: 0.5em)
  link(url)[#text(size: 8.5pt, fill: c2c-orange, weight: "semibold")[#coupures-url(label)]]
}

// Modules poses AU FIL DU TEXTE — expression la plus directe de l'ADN
// pixel-art (des modules, pas une enumeration separee par des points), et le
// seul agencement qui s'adapte VRAIMENT a son contenu.
//
// Des `box` inline, et non une grille a colonnes fixes : ils se replient comme
// des mots. Une competence tient donc sur une ligne, quinze en occupent trois,
// sans jamais la demi-rangee vide que laissait la grille (bug signale : « les
// blocs competences et equipe prennent trop de place [...] il faut que ça
// s'adapte au cas 1 competence ou 15, 2 membres ou 10 »).
//
// `leading: gap-cellules` — le blanc entre deux LIGNES de modules egale celui
// qui les separe horizontalement : la grille modulaire reste carree, quel que
// soit le nombre de replis.
// `text(spacing: gap-cellules)` — l'espace de mot separe deux modules
// voisins ; c'est aussi le seul separateur qui offre a Typst une occasion de
// couper la ligne (un `h()` fige, lui, ne s'y prete pas). Il est remis a sa
// valeur normale DANS chaque module : sans ca, une competence en deux mots
// (« Traitement d'image ») verrait son espace interne ecrase a 3pt.
#let module-inline(corps) = box(fill: c2c-tint, inset: (x: 6pt, y: 4pt))[
  #text(spacing: 100%)[#corps]
]

#let modules(items) = {
  set par(justify: false, leading: gap-cellules, spacing: 0pt)
  set text(size: 8.5pt, spacing: gap-cellules)
  items.map(t => module-inline(t)).join(" ")
}

// Meme rangee de modules pour l'equipe : un module par personne, nom en
// demi-gras et role en gris a la suite. Plus de pastille d'initiales de 18pt
// par membre — c'etait, avec l'amorce de sous-section, l'essentiel de la place
// perdue : dix membres imposaient dix rangees de 24pt, ils tiennent desormais
// sur deux ou trois lignes.
#let modules-equipe(equipe) = {
  set par(justify: false, leading: gap-cellules, spacing: 0pt)
  set text(size: 8.5pt, spacing: gap-cellules)
  equipe.map(m => {
    let role = m.at("role", default: "")
    module-inline[
      #text(weight: "semibold")[#m.at("nom")]#if role != "" [
        #text(fill: c2c-grey)[ · #role]
      ]
    ]
  }).join(" ")
}

// Micro-entete d'un bloc de qualification — la typographie d'un libelle de
// cellule de faits (6.5pt capitales espacees), pas le titre de 11pt d'une
// sous-section : competences et equipe prolongent la grille des faits, ils
// n'ouvrent pas un chapitre. L'amorce `sous-section` coutait a elle seule
// 20pt de blanc au-dessus et 11pt de titre, pour deux blocs de trois lignes.
#let micro-entete(label) = block(above: 0pt, below: 6pt, breakable: false, sticky: true)[
  #box(fill: c2c-orange, width: 4pt, height: 4pt, baseline: -0.5pt)
  #h(5pt)
  #text(size: 6.5pt, fill: c2c-grey, weight: "bold", tracking: 0.6pt)[#upper(label)]
]

// Legende d'un visuel mis en regard (cf. m-duo) : elle se pose sous le TEXTE
// du chapitre, JAMAIS sous l'image. Sous l'image, sa hauteur s'ajoutait a
// celle du visuel et bousculait la hauteur du bloc entier — un chapitre dont
// le visuel etait legende ne se calait plus sur son voisin (bug signale).
// Sous le texte, elle occupe une place que la colonne de texte a de toute
// façon, et la hauteur du bloc ne depend plus que du visuel.
//
// `cote-image` pose le tiret orange DU COTE OU SE TROUVE L'IMAGE, et cale la
// legende de ce cote : le tiret designe alors le visuel qu'il commente au
// lieu de pointer dans le vide.
//   · motif `duo` — texte a gauche, image a droite (aspects ergonomiques,
//     resultats & impact) : tiret A DROITE ;
//   · motif `duo-inverse` — image a gauche, texte a droite (aspects
//     visuels) : tiret A GAUCHE, comme partout ailleurs dans le document.
// Le cote suit donc la mise en page reelle, pas une liste de chapitres figee :
// l'alternance duo / duo-inverse depend de ceux qui portent un visuel (cf.
// reference_renderer._reshape_chapitres_pdf, `duo_bascule`), une liste
// nommant les chapitres se serait desynchronisee des qu'un visuel change de
// chapitre.
//
// « Environnement » n'est pas concerne : en motif `stack`, sa legende vit
// deja dans l'aplat, sous le texte et tiret a gauche (cf. m-stack).
#let legende-sous-texte(im, cote-image: left) = if im.at("legende", default: "") != "" [
  #v(6pt)
  #align(cote-image)[
    #if cote-image == right [
      #text(size: 9pt, fill: c2c-ink, weight: "bold")[#im.at("legende")]
      #h(6pt)
      #box(fill: c2c-orange, width: 14pt, height: 2pt, baseline: -3pt)
    ] else [
      #box(fill: c2c-orange, width: 14pt, height: 2pt, baseline: -3pt)
      #h(6pt)
      #text(size: 9pt, fill: c2c-ink, weight: "bold")[#im.at("legende")]
    ]
  ]
]

// Amorce avant visuel : meme tiret, mais en gras et AVANT l'image — c'est le
// traitement des visuels empiles (m-stack), ou chacun introduit son propos
// comme une sous-section plutot que de le commenter apres coup. Meme taille
// que `legende` (9pt) : toutes les legendes du document doivent rester aussi
// discretes les unes que les autres — mesure sur le rendu, une legende a
// 10pt paraissait plus grosse que les autres, uniformise au plus petit
// traitement.
#let legende-avant(im) = if im.at("legende", default: "") != "" [
  #box(fill: c2c-orange, width: 14pt, height: 2pt, baseline: -3pt)
  #h(6pt)
  #text(size: 9pt, fill: c2c-ink, weight: "bold")[#im.at("legende")]
  #v(4pt)
]

// Bande de pied d'un visuel empile debordant (cf. m-stack) : meme teinte que
// les chapitres identite (environnement, resultats), collee sous l'image
// (au-dessus) et ancree en pied de page reelle (en bas, cf. son usage avec
// `place(bottom, ...)`). Porte legende et pagination SUR UNE MEME LIGNE — pas
// le pied de page complet (ligne-pied, mention copyright comprise) : cette
// bande n'est pas l'encart de cloture du document, juste le pied d'un
// visuel, plus sobre.
#let bande-pied-ouverture(im) = pad(x: -marge-x)[
  #block(width: page-w, fill: c2c-peach, inset: (left: marge-x, right: marge-x, top: 8pt, bottom: 18pt))[
    #grid(
      columns: (1fr, auto),
      align: (left + horizon, right + horizon),
      if im.at("legende", default: "") != "" [
        #box(fill: c2c-orange, width: 14pt, height: 2pt, baseline: -3pt)
        #h(6pt)
        #text(size: 9pt, fill: c2c-ink, weight: "bold")[#im.at("legende")]
      ],
      pagination(),
    )
  ]
]

// =====================================================================
// REPERTOIRE DE MISE EN PAGE DES CHAPITRES
// Plus de numerotation par chapitre : le libelle porte seul l'entete. Chaque
// chapitre porte un aplat (trois leviers, decides par reference_renderer.py) :
//   · fill — gris par defaut, peche pour les chapitres identite (environnement,
//     resultats), jamais decide par la longueur du texte ;
//   · bleed — reserve a resultats : l'aplat deborde alors pleine largeur ;
//   · layout — full (texte seul), colonnes (texte tres long, sans visuel),
//     duo / duo-inverse (un visuel en regard, alterne d'un chapitre a
//     l'autre), stack (visuels empiles, HORS aplat, sous le texte).
// =====================================================================

// Regle transverse : un titre ne doit JAMAIS se retrouver seul en bas de
// page, separe de son texte — `sticky: true` est le mecanisme natif de Typst
// pour ca : un bloc sticky ne peut pas etre le dernier element d'une page ;
// s'il ne reste pas au moins un peu de ce qui suit, tout bascule ensemble.
#let titre-chapitre(label) = block(below: 8pt, breakable: false, sticky: true)[
  #text(weight: "bold", size: 11pt)[#label]
]

// Deux colonnes reellement equilibrees.
// `columns` ne repartit rien de lui-meme quand la hauteur du conteneur est
// libre : il remplit la premiere colonne, puis deborde dans la seconde. On
// mesure donc le texte sur la largeur d'UNE colonne et on borne le conteneur
// a la moitie de cette hauteur — la coupure tombe alors au milieu du texte.
#let deux-colonnes(texte, taille: 10pt) = context {
  let h = measure(block(width: demi)[#text(size: taille)[#texte]]).height
  block(width: 100%, height: h / 2 + 7pt)[
    #set par(justify: false)
    #columns(2, gutter: gouttiere)[#text(size: taille)[#texte]]
  ]
}

// Enveloppe partagee par tous les motifs : CHAQUE chapitre porte un aplat
// plein (gris par defaut, peche pour les chapitres identite) — mesure sur la
// reference, aucun chapitre n'y reste sur blanc. L'aplat reste confine aux
// marges du texte, SAUF quand `bleed` (reserve a resultats, qui ferme le
// document) : la TEINTE deborde alors pleine largeur (100% de la page, zero
// marge exterieure), mais la marge INTERNE (inset) reste identique a gauche
// et a droite (marge-x des deux cotes) — une premiere version laissait un
// inset droit nul (image collee au bord reel, contre la marge normale du
// texte a gauche) : asymetrie signalee et corrigee. Le debordement ne joue
// donc que sur la couleur de fond, jamais sur la position du texte ou de
// l'image.
// `pad` (et non `move`, qui ne fait que deplacer le rendu apres coup) : c'est
// une operation de mise en page a part entiere, la seule qui laisse un bloc
// teinte se scinder correctement sur plusieurs pages quand son contenu
// depasse la hauteur utile d'une page.
// `pied`, quand fourni (resultats uniquement, cf. chapitre()), s'ajoute sous
// `corps` mais DANS le meme aplat — l'encart de cloture porte alors son
// propre pied de page, a la place du pied de page normal (supprime a l'appel).
// `below` (motif stack uniquement) : 0pt quand un visuel doit venir se coller
// exactement au bord de l'aplat — sans ca, l'espacement habituel apres le
// bloc teinte laisse un blanc visible avant l'image (mesure sur la reference :
// aucun espace entre l'aplat et son premier visuel empile).
// `inset-bas` : replie l'inset inferieur (16pt par defaut, comme le superieur)
// quand ce meme premier visuel suit — la legende doit rester proche de son
// image, pas seulement l'aplat proche de l'image (cf. m-stack).
// `above` : espace avant l'aplat — 22pt entre deux chapitres, mais
// gap-cellules pour le bloc "Contexte complet du projet", qui prolonge la
// grille des faits (cf. gap-cellules).
// Inset haut du mode bleed : marge-resultats (et non 16pt comme un aplat
// confine) — l'aplat de cloture est le seul a porter des marges internes
// larges, pour centrer son contenu (cf. marge-resultats).
#let bloc-plein(corps, fill: c2c-tint, bleed: false, breakable: true, pied: none, below: 6pt, inset-bas: none, above: gap-chapitre, padding: padding-aplat) = {
  // `inset-bas: none` = "comme les trois autres cotes" : un aplat est carre
  // dans ses marges internes par defaut, et seul m-stack le replie (cf. sa
  // note) pour rapprocher son premier visuel.
  let inset-bas = if inset-bas == none { padding } else { inset-bas }
  let contenu = if pied != none { [#corps #pied] } else { corps }
  if bleed {
    pad(x: -marge-x)[
      #block(
        above: above, below: below, breakable: breakable,
        width: page-w, fill: fill,
        inset: (left: marge-x, right: marge-x, top: marge-resultats, bottom: 18pt),
      )[#contenu]
    ]
  } else {
    block(
      above: above, below: below, breakable: breakable,
      width: 100%, fill: fill,
      inset: (left: padding, right: padding, top: padding, bottom: inset-bas),
    )[#contenu]
  }
}

// Motif « full » — texte seul. Largeur plafonnee a texte-w UNIQUEMENT quand
// l'aplat deborde (resultats sans visuel) : le conteneur fait alors page-w,
// et sans ce plafond le texte s'etirerait jusqu'au bord reel de la page. Un
// aplat confine, lui, offre deja EXACTEMENT texte-w moins ses propres insets
// (16pt de chaque cote) : y fixer quand meme `width: texte-w` demandait donc
// 32pt de plus que la boite n'en offrait, et le texte debordait a droite du
// bloc teinte (mesure sur la reference — bug confirme). D'ou `100%` (relatif
// au conteneur, deja juste) quand non-bleed. `breakable: false` (motif
// stack) : l'aplat texte doit rester un bloc entier — sans ca, un visuel
// debordant place juste apres peut lui disputer l'espace de la page en cours
// et le texte deborde de sa teinte.
#let m-full(label, texte, fill: c2c-tint, bleed: false, pied: none, breakable: true, above: gap-chapitre, below: 6pt, padding: padding-aplat) = bloc-plein([
  #block(width: if bleed { texte-w } else { 100% })[
    #titre-chapitre(label)
    #text(size: corps-size)[#texte]
  ]
], fill: fill, bleed: bleed, pied: pied, breakable: breakable, above: above, below: below, padding: padding)

// Motif « colonnes » — le seul pave qui reste tres long sans visuel a placer.
#let m-colonnes(label, texte, fill: c2c-tint, bleed: false, pied: none) = bloc-plein([
  #block(width: if bleed { texte-w } else { 100% })[
    #titre-chapitre(label)
    #deux-colonnes(texte, taille: corps-size)
  ]
], fill: fill, bleed: bleed, breakable: false, pied: pied)

// Ratio hauteur/largeur d'un visuel, mesure une fois a une largeur de
// reference arbitraire (le ratio est constant quelle que soit cette largeur).
// Pas de `context` ici : ces deux fonctions appellent `measure()` directement
// et supposent deja executees depuis un bloc `context` appelant (image-libre,
// m-duo) — les envelopper ici imbriquerait un contexte dans un contexte, ce
// qui renvoie du contenu non resolu plutot qu'un nombre (erreur de
// compilation constatee : « cannot multiply content with float »).
#let ratio-image(fichier) = measure(image(fichier, width: 100pt)).height / 100pt

// Largeur qui donne `hauteur-cible` a un visuel, plafonnee a `largeur-max` :
// un visuel large (paysage) garde sa largeur max (sa hauteur naturelle est
// alors deja sous la cible, aucune raison de le retrecir) ; un visuel haut
// (portrait) est retreci pour ne pas depasser la hauteur cible. Jamais
// l'inverse (agrandir au-dela de largeur-max) : ce n'est qu'un plafond.
#let largeur-pour-hauteur(fichier, hauteur-cible, largeur-max) = calc.min(largeur-max, hauteur-cible / ratio-image(fichier))

// Largeur exacte disponible pour l'image du motif duo : le conteneur de
// bloc-plein (texte-w hors bleed ; texte-w egalement en bleed, mais avec de
// plus petits insets, cf. bloc-plein) moins la colonne de texte fixe et la
// gouttiere. Calcul explicite (plutot que 100% relatif a la cellule de
// grille) : necessaire pour que `largeur-pour-hauteur` (mode fit-hauteur)
// connaisse le plafond de largeur avant de choisir une image plus etroite.
#let largeur-image-duo(bleed, texte-col-w: duo-texte-w) = (if bleed { texte-w } else { texte-w - 32pt }) - texte-col-w - gouttiere

// Recadrage centre a un ratio cible (largeur/hauteur) — aspects
// ergonomiques / aspects visuels (demande explicite, maquette fournie :
// 328/246). Fonction "nue" (pas de context a elle) : appelee depuis le
// context de bloc-visuel, comme ratio-image/largeur-pour-hauteur plus haut.
// Le contenu `place` porte TOUJOURS une boite explicite a sa taille naturelle
// (`box(width: .., height: ..)`) : sans elle, une image plus HAUTE que la
// boite de rognage fait emettre par Typst DEUX rectangles de clip — celui de
// la boite, et le meme redecale de `dy` — dont l'intersection rogne bien plus
// que demande (mesure sur le rendu : 138pt visibles au lieu des 186pt du
// format cible, pour l'image libre). Une image plus LARGE que haute ne
// declenchait pas le defaut (un seul clip, decalage horizontal), d'ou son
// passage inapercu tant que seuls les visuels 4:3 des chapitres utilisaient
// cette fonction.
#let image-recadree(fichier, largeur, ratio-cible) = {
  let ratio = ratio-image(fichier)
  let hauteur = largeur * ratio-cible
  box(width: largeur, height: hauteur, clip: true)[
    #if ratio >= ratio-cible [
      // plus haut que la cible : rogne haut/bas, centre vertical
      #place(top + center, dy: -(largeur * ratio - hauteur) / 2)[
        #box(width: largeur, height: largeur * ratio)[#image(fichier, width: largeur)]
      ]
    ] else [
      // plus large que la cible : rogne gauche/droite, centre horizontal
      #place(left + top, dx: -(hauteur / ratio - largeur) / 2)[
        #box(width: hauteur / ratio, height: hauteur)[#image(fichier, width: hauteur / ratio)]
      ]
    ]
  ]
}
// Ratio cible (hauteur/largeur) et debord en largeur pour aspects
// ergonomiques/visuels — cf. maquette utilisateur : 328x246 (4:3 paysage),
// l'image sort du bloc aplat et mange une partie (pas la totalite, a la
// difference de "resultats") de la marge droite de la page ; l'aplat, lui,
// reste confine et centre (bleed: false, inchange).
#let ratio-image-large-format = 246.0 / 328.0
// Taille cible ~328x246px @ 96dpi (1px = 0.75pt, cf. hauteur-min-image-duo
// plus haut pour la meme conversion) — l'image ne grandit plus pour remplir
// sa colonne, elle vise cette taille precise (demande explicite).
#let largeur-image-large-format = 246pt
// Gap entre l'image et le bord PHYSIQUE de la page — iso au gap entre deux
// chapitres (bloc-plein, espace "above"), pour ne pas coller l'image au
// bord (demande explicite, capture a l'appui).
#let gap-bord-image-large-format = 22pt
// Gap entre le texte et l'image — iso au padding standard d'un chapitre
// confine (aspects techniques, etc. : 16pt de chaque cote, cf. bloc-plein),
// pas le gouttiere des autres duos (demande explicite).
#let gouttiere-image-large-format = 16pt

// Motif « duo » — texte et visuel en regard. TOUS DEUX dans le meme aplat
// (rien ne reste sur blanc a cote d'un chapitre teinte).
// `fit-hauteur` (aspects ergonomiques / aspects visuels uniquement, cf.
// maquette utilisateur) : visuel a taille FIXE (image-recadree, 4:3), qui
// sort du bloc aplat (celui-ci reste confine/centre, bleed: false) et mange
// une partie de la marge de la page, en s'arretant a gap-bord-image-large-
// format du bord physique. Le texte REMPLIT tout le reste de la largeur
// (colonne derivee, pas fixe) avec un gutter fixe (gouttiere-image-large-
// format) vers l'image, et se centre verticalement (align: horizon).
// `bleed` (resultats uniquement, cf. reference_renderer.py — seul chapitre
// avec ce fanion) : colonne de texte reduite a duo-texte-w-resultats pour
// que le visuel occupe EXACTEMENT la moitie du bloc (texte-w/2), PUIS
// elargi de marge-x pour deborder jusqu'au bord physique droit de la page
// (demande explicite) — largeur-image-duo(bleed:true) s'arrete deja a
// l'inset droit du bloc-plein (page-w - marge-x), jamais clippe : lui
// ajouter marge-x de largeur suffit a le franchir et atteindre exactement
// le bord reel, sans decalage a calculer.
#let m-duo(label, texte, im, inverse: false, fill: c2c-tint, bleed: false, pied: none, fit-hauteur: false) = {
  // La legende du visuel fait partie du bloc TEXTE (cf. legende-sous-texte) :
  // c'est ce qui rend la hauteur du bloc independante du fait qu'un visuel
  // soit legende ou non.
  let bloc-texte = [
    #titre-chapitre(label)
    #text(size: corps-size)[#texte]
    #legende-sous-texte(im, cote-image: if inverse { left } else { right })
  ]
  let corps = if fit-hauteur {
    // IMPORTANT : une grille dont les colonnes EXPLICITES (longueurs fixes)
    // somment plus que son conteneur ne deborde pas comme un box/image tout
    // seul — Typst la pousse purement et simplement sur une page suivante
    // (verifie a l'usage, aucune image visible). Le debord doit donc rester
    // une colonne `1fr` (qui absorbe "le reste", jamais une longueur fixe en
    // trop) contenant un CONTENU plus large qu'elle : seul le contenu
    // deborde alors, pas la grille — meme mecanisme que "resultats" plus
    // bas, deja verifie correct.
    let base-w = texte-w - 32pt
    let debord = 16pt + marge-x - gap-bord-image-large-format
    let largeur-cible = largeur-image-large-format * echelle-duo
    // Largeur de colonne texte telle que le 1fr restant, SANS debord, vaut
    // exactement (largeur-cible - debord) : le contenu (rendu a largeur-
    // cible, donc `debord` de plus que ce que le 1fr alloue) deborde alors
    // pile de `debord`.
    let texte-col-w = base-w - (largeur-cible - debord) - gouttiere-image-large-format
    let bloc-visuel = context {
      align(if inverse { right } else { left })[#image-recadree(im.at("fichier"), largeur-cible, ratio-image-large-format)]
    }
    [
      #set par(justify: false)
      #grid(
        columns: if inverse { (1fr, texte-col-w) } else { (texte-col-w, 1fr) },
        column-gutter: gouttiere-image-large-format,
        align: if inverse { (top, horizon) } else { (horizon, top) },
        ..if inverse { (bloc-visuel, bloc-texte) } else { (bloc-texte, bloc-visuel) },
      )
    ]
  } else {
    let texte-col-w = if bleed { duo-texte-w-resultats } else { duo-texte-w }
    let largeur-max = largeur-image-duo(bleed, texte-col-w: texte-col-w)
    let bloc-visuel = context {
      // Le visuel du chapitre de cloture (bleed) est EXCLU de echelle-duo :
      // son bord droit doit venir se coller au bord droit du bloc, donc au
      // bord physique droit de la page (demande explicite, maquette fournie).
      // Comme il est cale a GAUCHE de la colonne 1fr qui le contient et
      // deborde par la droite, tout facteur < 1 retirait de la largeur par la
      // droite — et decollait l'image du bord (constate : la boucle de
      // remplissage retenait echelle-duo = 0.8, l'image s'arretait a ~19pt
      // du bord). La boucle garde ce levier pour les autres duos.
      let largeur = if bleed { largeur-max + marge-x } else { largeur-max * echelle-duo }
      image(im.at("fichier"), width: largeur)
    }
    // Le chapitre de cloture (seul `bleed`) centre son texte sur la hauteur du
    // bloc, comme le font deja les duos a visuel fixe (cf. la branche
    // fit-hauteur plus haut) : cale en haut, il laissait sous lui un vide
    // d'autant plus visible que l'aplat, lui, descend jusqu'au bord de la page
    // (demande explicite). Le visuel, lui, reste cale en haut — c'est le bord
    // superieur de l'aplat qu'il doit suivre.
    let align-texte = if bleed { horizon } else { top }
    [
      #set par(justify: false)
      #grid(
        columns: if inverse { (1fr, texte-col-w) } else { (texte-col-w, 1fr) },
        column-gutter: gouttiere,
        align: if inverse { (top, align-texte) } else { (align-texte, top) },
        ..if inverse { (bloc-visuel, bloc-texte) } else { (bloc-texte, bloc-visuel) },
      )
    ]
  }
  bloc-plein(corps, fill: fill, bleed: bleed, breakable: false, pied: pied)
}

// Image "libre" : aucun chapitre, aucun aplat — juste le visuel, en pleine
// largeur PHYSIQUE de la page (page-w, bords gauche ET droit du document, pas
// la mesure de texte : demande explicite, maquette fournie), au format
// nominal 911 x 370 px.
//
// Ce format n'est plus qu'un CONSEIL cote saisie (l'interface l'annonce mais
// ne le refuse plus) : c'est le recadrage centre ci-dessous qui garantit le
// cadre, quel que soit le fichier fourni — jamais une deformation. Un visuel
// hors format n'est donc pas un probleme, il est rogne.
//
// Cette hauteur nominale est un PLANCHER, pas une valeur figee : l'image
// libre d'ouverture s'en ecarte vers le haut quand la page lui laisse de la
// place (cf. image-libre-ouverture). Dans le flux ordinaire — fiche dense,
// type Rennes — elle reste exactement celle du format cible, et la boucle de
// verification ne la rogne pas (cf. image-libre-echelle plus haut).
#let ratio-image-libre = 370.0 / 911.0

#let hauteur-image-libre = page-w * ratio-image-libre * image-libre-echelle

// Le visuel seul, pleine largeur physique, sans reserver sa place dans le
// flux : `place` — c'est ce qui permet au chapeau de venir se poser DESSUS
// (cf. chapeau-sur-image). `dx: -marge-x` le ramene au bord gauche reel.
// `dy` sert au decalage vertical sous le chapeau (cf.
// decalage-image-chapeau) ; nul quand l'image est posee seule.
// `hauteur` : hauteur RENDUE du visuel. Nulle part ailleurs qu'en ouverture
// aeree elle ne s'ecarte de la hauteur nominale — c'est ce parametre qui
// permet a l'image de prendre la place que la page lui laisse, en devoilant
// davantage du fichier plutot qu'en l'agrandissant.
#let pave-image-libre(im, dy: 0pt, hauteur: none) = {
  let h = if hauteur == none { hauteur-image-libre } else { hauteur }
  place(top + left, dx: -marge-x, dy: dy)[
    #image-recadree(im.at("fichier"), page-w, h / page-w)
  ]
}

// Decalage vertical entre le haut de l'aplat du chapeau et le haut de l'image
// vitrine qui court derriere lui : le haut de l'image tombe sur le MILIEU
// vertical de l'aplat (demande explicite). Une proportion, donc, et pas une
// longueur : le decalage suit la hauteur reelle du chapeau, quelle que soit la
// longueur du texte ou la taille de corps retenue par la boucle de
// remplissage. Calcule dans chapeau-sur-image, seul endroit ou cette hauteur
// est mesuree.
#let fraction-decalage-image-chapeau = 0.5

// Legende d'un visuel pleine largeur : elle reste, elle, dans la mesure de
// texte — comme toutes les autres du document. `above: 4pt` porte ici
// l'espace que `legende` insere d'ordinaire elle-meme (son v(4pt)) : le
// visuel etant un bloc a part entiere, l'espacement de bloc par defaut s'y
// substituerait sinon, et eloignerait la legende de son visuel.
#let legende-sous-image(im) = if im.at("legende", default: "") != "" {
  block(above: 4pt, below: 0pt)[
    #box(fill: c2c-orange, width: 14pt, height: 2pt, baseline: -3pt)
    #h(6pt)
    #text(size: 9pt, fill: c2c-ink, weight: "bold")[#im.at("legende")]
  ]
}

// Image libre POSEE DANS LE FLUX, seule : le cas ou elle prend la place d'un
// chapitre-image manquant (cf. reference_renderer._reshape_chapitres_pdf).
#let image-libre(bl) = context {
  let im = bl.at("image")
  // gap-standard (cf. plus haut) : meme espace que celui utilise pour
  // marge-bas-page, demande explicite.
  block(above: gap-standard, below: gap-standard, breakable: false, width: 100%, height: hauteur-image-libre)[
    #pave-image-libre(im)
  ]
  legende-sous-image(im)
}

// Chapeau ("Contexte complet du projet") SUPERPOSE a l'image libre : l'aplat
// gris se pose SUR le visuel, qui court pleine largeur derriere lui et se
// prolonge sous lui (demande explicite, maquette fournie — « l'image libre
// apparait sous le bloc aplat gris contexte complet »). Les deux ne sont donc
// pas deux elements successifs du flux mais un seul pave compose.
//
// Un `block` de hauteur explicite avec deux `place` empiles, et non un flux
// normal : c'est le seul moyen d'avoir le visuel HORS flux (pour que l'aplat
// se pose dessus) tout en reservant quand meme la hauteur qu'il occupe, pour
// que le chapitre suivant ne le chevauche pas.
// Hauteur = la plus grande des deux, mesuree : un chapeau tres long depasse
// l'image et doit alors imposer sa propre hauteur ; a l'inverse, l'image
// rognee par la boucle de remplissage reduit bien la hauteur du pave — c'est
// ce qui garde le pave a la hauteur juste si l'echelle change un jour.
#let chapeau-sur-image(label, texte, bl) = context {
  let im = bl.at("image")
  let aplat = m-full(label, texte, above: 0pt, padding: padding-chapeau)
  let h-aplat = measure(block(width: texte-w)[#aplat]).height
  let decalage = h-aplat * fraction-decalage-image-chapeau
  block(
    above: gap-cellules, below: gap-standard, breakable: false,
    width: 100%,
    height: calc.max(h-aplat, decalage + hauteur-image-libre),
  )[
    #pave-image-libre(im, dy: decalage)
    #place(top + left)[#aplat]
  ]
  legende-sous-image(im)
}

// Visuel empile : HORS aplat, sur blanc, largeur confinee aux marges ou
// debordante selon `im.bleed` (decide par reference_renderer.py — le premier
// confine, les suivants alternent) — sans aucune marge interne dans les deux
// cas : l'image touche exactement les bords de sa largeur. `colle` (le
// premier de la pile) supprime l'espace au-dessus : rien ne doit se voir
// entre l'aplat et lui. `legende` : le premier visuel de la pile est presente
// par sa legende DANS l'aplat (cf. m-stack, mesure sur la reference — la
// legende du visuel colle fait partie du bloc teinte, pas du blanc en
// dessous) ; seuls les visuels suivants portent encore leur propre amorce
// ici. Le recadrage (boucle de remplissage) est deja applique au fichier
// lui-meme cote Python.
#let visuel-empile(im, colle: false, legende: true) = block(above: if colle { 0pt } else { 16pt }, below: 0pt, breakable: false)[
  #if legende [#legende-avant(im)]
  #if im.at("bleed", default: false) [
    #move(dx: -marge-x)[#box(width: page-w)[#image(im.at("fichier"), width: 100%)]]
  ] else [
    #image(im.at("fichier"), width: 100%)
  ]
]

// Visuel pleine largeur rogne a une hauteur IMPOSEE, le haut conserve — c'est
// lui qui porte le propos. Sert au visuel du chapitre "Environnement", dont la
// hauteur est calculee pour remplir exactement la place restante sur la page
// (cf. m-stack). La boite interieure explicite est indispensable : sans elle,
// une image plus haute que sa boite de rognage fait emettre par Typst deux
// clips decales (cf. la note de image-recadree).
#let visuel-rogne(fichier, hauteur) = box(width: texte-w, height: hauteur, clip: true)[
  #place(top + left)[
    #box(width: texte-w, height: texte-w * ratio-image(fichier))[#image(fichier, width: texte-w)]
  ]
]

// Plancher de rognage du visuel empile, en fraction de sa hauteur naturelle :
// en dessous, l'image ne dit plus rien. Quand la place restante n'atteint meme
// pas ce plancher, on garde le plancher et le chapitre bascule en page
// suivante.
//
// C'est un LEVIER de la boucle de verification (cf. PLANCHER_VISUEL_LADDER et
// la sequence de repli d'« Environnement » cote Python) : au nominal (1.0),
// aucun rognage n'est tolere — le chapitre bascule en page suivante plutot
// que de rogner — et ce n'est qu'apres avoir epuise les leviers de mise en
// page (espaces, puis rognage de l'image libre, puis collage au pied de page
// reel, cf. environnement-full-pied) que ce plancher cede a son tour, PLAFONNE
// a 20 % de rognage, puis 30 % au palier le plus dense. Demande explicite :
// un plafond strict, jamais un rognage qui rend le visuel illisible.
#let plancher-visuel-empile = doc.at("plancher_visuel_empile", default: 1.0)

// Coupe-circuit de securite, DECIDE COTE PYTHON (converger, reference_renderer.py) :
// l'ancrage bas d'« Environnement » (pave-ancre, cf. plus bas) repose sur un
// `layout()` qui mesure la place restante puis y cale le visuel — mecanique
// deja fragile (quatre approches anterieures abandonnees, cf. les notes de
// pave-ancre) qui, sur certaines fiches a redaction longue COMBINEE a un bloc
// de qualification (competences/equipe) au-dessus, produit un defaut Typst
// mesure sur le rendu : pied de page duplique et pagination incoherente (bug
// signale, ex. catalogue cartes.gouv). La boucle de verification recompile
// alors une fois avec ce fanion actif pour verifier si le defaut disparait
// (verifie : il disparait) et, si oui, retient ce reglage — l'ancrage bas
// n'est alors qu'une preference cosmetique face a un document correct.
#let desactiver-ancre-environnement = doc.at("desactiver_ancre_environnement", default: false)

// Leviers de la sequence de repli du visuel « Environnement » (cf.
// PLANCHER_VISUEL_LADDER, IMAGE_LIBRE_CROP_LADDER et la sequence elle-meme
// cote Python, render_pdf._converger_un_passage) — decides EXCLUSIVEMENT la,
// jamais au hasard ici :
//   · plancher-visuel-empile (deja defini plus haut) borne le rognage du
//     visuel « Environnement » lui-meme ;
//   · environnement-full-pied colle le pave ancre au bord bas REEL de la
//     page (comme le fait deja resultats, cf. chapitre()) : plus de marge
//     blanche ni de pied de page normal sur cette page-la, la place gagnee
//     revient au visuel. Repli AVANT le rognage extreme : une fiche sans
//     pied de page visible sur une seule page vaut mieux qu'un visuel
//     illisible.
//   · masquer-image-libre abandonne l'image "libre" (vitrine) posee sous le
//     chapeau — dernier repli qui retire du contenu plutot que de comprimer
//     encore, cf. la sequence Python.
#let environnement-full-pied = doc.at("environnement_full_pied", default: false)
#let masquer-image-libre = doc.at("masquer_image_libre", default: false)

// Ancrage d'un chapitre sur le BAS de la zone de contenu, le blanc restant se
// reportant AU-DESSUS de lui (demande explicite pour "Environnement").
//
// MECANIQUE : un bloc de hauteur `1fr` — il occupe donc, par definition, tout
// ce qui reste de la page — et `layout` pour connaitre cette hauteur resolue,
// ce qui permet d'y caler le chapitre en bas et de dimensionner son visuel
// pour remplir la place exactement. Aucune arithmetique de position.
//
// Quatre approches ont echoue avant celle-la, chacune pour une raison propre a
// Typst — a ne pas re-essayer :
//   · `v(1fr)` — le ressort et `here()`, dans un meme `context`, se
//     determinent mutuellement (la place restante depend de l'ancrage, qui
//     depend de la place restante) : la mise en page se stabilisait sur des
//     valeurs fausses (visuel rogne a 175pt pour 265pt disponibles). Et un
//     ressort ne prend que ce qui reste APRES le flux : des qu'un chapitre
//     suivant se glissait sur la meme page, il tombait a zero et le chapitre
//     n'etait plus ancre du tout.
//   · un comblement calcule pose en `v()` — une spacing est ESCAMOTEE par
//     Typst en tete de page : le chapitre qui basculait se retrouvait colle en
//     haut de la page suivante, ancrage perdu.
//   · un bloc de hauteur calculee depuis `here()` — `here().position().y` NE
//     COMPTE PAS la spacing `below` de l'element precedent (mesure sur le
//     rendu : 14.7pt de moins que la position reelle). Le bloc, trop haut de
//     ces 14.7pt, ne tenait plus sur la page et basculait entierement.
//   · `place(bottom, float: true)` — un float reserve sa hauteur dans le flux
//     mais laisse le chapitre suivant occuper l'espace au-dessus de lui.
//
// `here()` ne sert plus qu'a un go/no-go PESSIMISTE (cf. plus bas) : jamais a
// dimensionner.
#let bas-zone-contenu = page-h - marge-bas-page

// Marge basse effective sous un chapitre ancre : le pied de page menage deja
// gap-standard de blanc au-dessus de lui (cf. footer-descent), seul le
// complement est a reserver ici pour atteindre marge-env-bas au total.
// Nulle en mode « full pied » (environnement-full-pied) : le pave colle alors
// au bord bas reel, aucun blanc ni pied de page normal ne subsiste sur cette
// page (cf. pave-ancre, parametre `bleed`).
#let pad-bas-ancrage = if environnement-full-pied { 0pt } else { calc.max(0pt, marge-env-bas - gap-standard) }

// `construire` reçoit la hauteur disponible et rend le contenu a caler en bas.
//
// Le `pagebreak(weak: true)` qui suit le pave n'est pas une precaution : il
// est CONSTITUTIF du mecanisme. `height: 1fr` vaut « ce qui reste de la page
// apres tout le contenu non fractionnaire qu'elle porte », et non « le reste
// de la page a partir d'ici » : sans ce saut, le chapitre suivant se glissait
// sur la meme page et le pave se retrouvait reduit a la portion congrue
// (mesure sur le rendu : 8pt de visuel visible pour un pave de 175pt). Un
// chapitre ancre FERME donc sa page — ce qui est de toute façon le sens de la
// demande (« le bloc environnement doit etre ancre au bas du document »).
// `weak: true` : aucun saut si la page est deja vierge, donc jamais de page
// blanche.
//
// `bleed` (repli « full pied de page », cf. environnement-full-pied) : le
// pave gagne exactement `marge-bas-page` de hauteur supplementaire — celle
// que le traitement normal laisse a la marge de pied — et deborde d'autant
// dans cette marge via un `pad` negatif, EXACTEMENT le mecanisme deja utilise
// par le chapitre de cloture (resultats, cf. chapitre()) pour coller un pave
// au bord bas physique de la page. Le pied de page normal, recouvert, est
// supprime sur cette page (cf. supprimer-pied) pour ne pas se superposer au
// visuel.
#let pave-ancre(construire, bleed: false) = {
  block(
    above: 0pt, below: 0pt, breakable: false, width: 100%, height: 1fr,
  )[
    #layout(taille => {
      let h-boite = if bleed { taille.height + marge-bas-page } else { taille.height }
      // Le `box` a la hauteur resolue est indispensable : sans lui, `place`
      // s'applique a une boite de hauteur nulle et le contenu remonte
      // AU-DESSUS du pave (verifie a l'usage).
      let boite = box(width: 100%, height: h-boite)[
        #place(bottom + left, dy: -pad-bas-ancrage)[#construire(h-boite)]
      ]
      if bleed { pad(bottom: -marge-bas-page)[#boite] } else { boite }
    })
  ]
  if bleed { supprimer-pied() }
  pagebreak(weak: true)
}

// Estimation PESSIMISTE de la place restante, pour decider si l'ancrage est
// tenable ici : `here()` sous-compte la spacing `below` du bloc precedent, on
// retranche donc la plus grande que le gabarit puisse poser. Sous-estimer
// fait renoncer a l'ancrage sur une page ou il aurait tenu — le chapitre
// bascule alors normalement et c'est la boucle de verification qui resserre
// ce qui precede. Sur-estimer ferait deborder le pave sur le contenu
// precedent, sans recours : le biais est donc volontairement de ce cote.
#let place-restante-pessimiste() = (
  bas-zone-contenu - here().position().y - calc.max(gap-standard, gap-chapitre)
)

// Pave occupant tout le reste de la page, contenu CENTRE dans ce reste : le
// blanc disponible se repartit alors a parts EGALES au-dessus et en dessous
// (demande explicite pour l'image libre d'ouverture). Meme mecanique que
// `pave-ancre` — `height: 1fr` pour prendre tout le reste, `layout` pour
// connaitre la hauteur resolue, `place` dans une boite a cette hauteur — et,
// pour exactement la meme raison, le meme `pagebreak(weak: true)` : `1fr` vaut
// « ce qui reste de la page apres TOUT son contenu non fractionnaire », pas
// « le reste a partir d'ici ». Sans ce saut, le chapitre suivant se glisse sur
// la page et le pave se retrouve reduit a la portion congrue.
#let pave-centre(contenu) = {
  block(
    above: 0pt, below: 0pt, breakable: false, width: 100%, height: 1fr,
  )[
    #layout(taille => box(width: 100%, height: taille.height)[
      #place(horizon + left)[#contenu]
    ])
  ]
  pagebreak(weak: true)
}

// Image libre « d'ouverture » : elle FERME la page 1 — tous les chapitres
// commencent page 2 — et se centre dans le blanc laisse entre le bloc de
// contexte et le pied de page.
//
// Demande explicite pour les fiches dont le chapitre « Environnement » n'est
// pas redige (cf. reference_renderer._reshape_chapitres_pdf, fanion
// `ouverture_aeree`) : l'image prend alors la place du tout premier chapitre,
// et le suivant venait se glisser juste dessous. La page 1 se retrouvait deux
// fois plus dense que la page 2 — deux chapitres serres sous l'image d'un
// cote, deux chapitres et beaucoup de blanc de l'autre. Le saut de page
// retablit l'equilibre, et le centrage emploie le blanc gagne a aerer la page
// plutot qu'a le laisser s'accumuler sous l'image.
//
// Go/no-go PESSIMISTE (meme estimation que `ancrer-bas`, cf.
// place-restante-pessimiste) avant d'engager le centrage : si le pave ne tient
// pas ici, on retombe EXACTEMENT sur le comportement ordinaire (image dans le
// flux, aucun saut de page). Reporter l'image seule page 2 pousserait les
// chapitres page 3 — le remede serait pire que le mal.
#let image-libre-ouverture(bl) = context {
  let im = bl.at("image")
  let fichier = im.at("fichier")
  let place-dispo = place-restante-pessimiste()
  let h-legende = measure(block(width: texte-w)[#legende-sous-image(im)]).height

  // Hauteur du visuel, entre trois bornes :
  //   · PLANCHER — la hauteur nominale (911 x 370). L'image ne se retrecit
  //     jamais en dessous, meme sur une page avare.
  //   · PLAFOND  — sa hauteur NATURELLE a pleine largeur de page. Au-dela il
  //     faudrait l'agrandir : du flou, exactement ce qu'on vient de corriger
  //     ailleurs. C'est aussi le point ou le recadrage disparait tout a fait —
  //     l'image est alors montree en entier.
  //   · la place que la page laisse reellement, respiration deduite.
  // Un fichier au format conseille reste donc a sa hauteur nominale ; un
  // fichier plus haut (16:9, 4:3, capture verticale) profite de la place —
  // c'est ce que la levee de la contrainte de format rend possible.
  let h-naturelle = page-w * ratio-image(fichier)
  let h-max = place-dispo - 2 * gap-standard - h-legende
  let hauteur = calc.max(hauteur-image-libre, calc.min(h-max, h-naturelle))

  let contenu = [
    #block(above: 0pt, below: 0pt, breakable: false, width: 100%, height: hauteur)[
      #pave-image-libre(im, hauteur: hauteur)
    ]
    #legende-sous-image(im)
  ]
  if place-dispo >= measure(block(width: texte-w)[#contenu]).height {
    pave-centre(contenu)
  } else {
    image-libre(bl)
  }
}

#let ancrer-bas(contenu) = context {
  let h = measure(block(width: texte-w)[#contenu]).height
  // Meme bonus qu'au go/no-go de m-stack (cf. sa note) : le mode « full pied »
  // gagne marge-bas-page en bleedant dans la marge de pied, ce que ce go/no-go
  // doit anticiper pour laisser l'ancrage s'engager.
  let bonus-full-pied = if environnement-full-pied { marge-bas-page } else { 0pt }
  if place-restante-pessimiste() - gap-chapitre - pad-bas-ancrage + bonus-full-pied >= h {
    pave-ancre(_ => contenu, bleed: environnement-full-pied)
  } else {
    v(gap-chapitre)
    contenu
  }
}

// Motif « stack » — plusieurs visuels ne se mettent pas en regard sans se
// rapetisser l'un l'autre : le texte reste seul dans l'aplat (comme m-full,
// mais jamais scinde : cf. sa note `breakable: false`), les visuels
// s'empilent ensuite HORS aplat, chacun introduit par sa propre amorce
// (legende-avant) en gras. Un visuel debordant (`bleed`) s'ancre en pied de
// page reelle, comme le visuel d'ouverture, mais SANS forcer de saut de
// page : s'il reste de la place, le chapitre suivant vient normalement la
// remplir (c'est ce que fait la reference) ; sinon il continue naturellement
// page suivante, faute de place.
// `ancre-bas` : le chapitre est cale en BAS de la page courante, le blanc
// disponible se reportant AU-DESSUS de lui (demande explicite : « le bloc
// environnement doit etre ancre au bas du document, [...] l'espace libre se
// fait donc entre l'image libre et le debut du bloc environnement »). Un
// ressort `v(1fr)` et non un `place(bottom, float: true)` : le float
// resoudrait `here()` a sa position FINALE (en bas de page), et le budget de
// recadrage ci-dessous — qui se calcule justement a partir de cette position
// — serait alors quasi nul. Le ressort, lui, est emis APRES la mesure : la
// place restante est celle qui precede l'ancrage, donc bien tout l'espace
// que le chapitre peut occuper.
#let m-stack(label, texte, images, fill: c2c-tint, bleed: false, pied: none, ancre-bas: false) = {
  // Le premier visuel de la pile est glisse dans l'aplat lui-meme : seule sa
  // legende (mesure sur la reference — le bloc teinte contient le titre, le
  // texte ET la legende du premier visuel) ; l'image reste hors aplat, mais
  // vient se coller exactement a son bord (cf. `below: 0pt` plus bas et
  // `colle` sur visuel-empile).
  let premiere = if images.len() > 0 { images.at(0) } else { none }
  let corps = [
    #block(width: if bleed { texte-w } else { 100% })[
      #titre-chapitre(label)
      #text(size: corps-size)[#texte]
    ]
    // Espace supplementaire avant la legende : elle doit se lire comme
    // l'amorce du visuel qui suit, pas comme la fin du paragraphe.
    #if premiere != none [#v(6pt) #legende-avant(premiere)]
  ]
  let below = if premiere != none { 0pt } else { 6pt }
  let inset-bas = if premiere != none { 8pt } else { 16pt }
  // "environnement" (seul chapitre en stack a ce jour) porte un visuel pleine
  // largeur dont la hauteur est CALCULEE, pas choisie dans une echelle : il
  // remplit exactement la place laissee libre sur la page par ce qui precede.
  //
  // Une version anterieure choisissait, parmi neuf variantes pre-rognees, la
  // premiere qui tenait dans une place restante estimee a la main (somme des
  // marges et insets de bloc-plein). L'estimation etait fausse — Typst
  // escamote la spacing de tete d'un bloc, que le calcul comptait quand meme —
  // et la granularite de 3 % ajoutait son propre reliquat : jusqu'a 80pt de
  // blanc inutilise restaient sous l'image (bug signale : « il persiste encore
  // beaucoup de blanc entre l'image vitrine et le bloc environnement »).
  //
  // Ici, plus d'arithmetique de chrome : on MESURE l'assemblage complet avec
  // une image de hauteur nulle, ce qui donne la hauteur reelle de l'aplat,
  // insets et espacements compris. La hauteur d'image est alors le
  // complement exact — bornee par la hauteur naturelle du visuel (jamais
  // d'agrandissement) et par le plancher de rognage.
  if premiere != none {
    context {
      let fichier = premiere.at("fichier")
      let assembler(hauteur-image) = block(above: 0pt, below: 0pt, breakable: false)[
        #bloc-plein(corps, fill: fill, bleed: bleed, breakable: false, below: below, inset-bas: inset-bas, above: 0pt)
        #visuel-rogne(fichier, hauteur-image)
      ]
      // Hauteur de l'aplat seul, MESUREE et non deduite de ses insets :
      // l'ancienne arithmetique de chrome comptait une spacing que Typst
      // escamote, et se trompait d'une vingtaine de points.
      let h-sans-image = measure(block(width: texte-w)[#assembler(0pt)]).height
      let h-naturelle = texte-w * ratio-image(fichier)

      // Place que le visuel pourrait occuper ici, au pire (cf.
      // place-restante-pessimiste) : sert au seul go/no-go de l'ancrage.
      let place-visuel-min = (
        place-restante-pessimiste() - gap-chapitre - pad-bas-ancrage - h-sans-image
      )
      // Bonus du mode « full pied » (environnement-full-pied) : `pave-ancre`
      // gagne exactement `marge-bas-page` de hauteur en bleedant dans la marge
      // de pied (cf. sa note, parametre `bleed`) — mais CE go/no-go, lui, ne le
      // sait pas : sans ce bonus, une fiche qui echoue deja au plancher de
      // rognage le plus lache echoue aussi a TOUS les paliers suivants qui ne
      // font que coller au pied de page, puisqu'on n'entre alors jamais dans
      // `pave-ancre` pour en profiter (bug signale : la sequence de repli
      // saute le collage au pied et va directement retirer l'image libre).
      // N'entre PAS dans `place-visuel-min` lui-meme : ce dernier sert aussi a
      // dimensionner le visuel de la branche SANS ancrage juste en dessous,
      // qui ne beneficie d'aucun bleed.
      let bonus-full-pied = if environnement-full-pied { marge-bas-page } else { 0pt }
      if ancre-bas and place-visuel-min + bonus-full-pied >= h-naturelle * plancher-visuel-empile {
        pave-ancre(h-pave => {
          // Hauteur EXACTE du pave (resolue par `layout`) : le visuel remplit
          // toute la place laissee par l'aplat et les deux marges — jamais
          // plus que sa hauteur naturelle, aucun agrandissement.
          let place-visuel = h-pave - gap-chapitre - pad-bas-ancrage - h-sans-image
          assembler(calc.min(h-naturelle, place-visuel))
        }, bleed: environnement-full-pied)
      } else {
        // Pas d'ancrage : le visuel se contente de la place restante sur la
        // page courante, au plancher de rognage pres. Le chapitre bascule de
        // lui-meme s'il ne tient pas, et c'est a la boucle de verification de
        // resserrer ce qui precede.
        v(gap-chapitre)
        assembler(calc.max(
          h-naturelle * plancher-visuel-empile,
          calc.min(h-naturelle, place-visuel-min),
        ))
      }
    }
  } else {
    // Chapitre sans visuel : seul l'aplat, ancre ou non.
    let aplat = bloc-plein(corps, fill: fill, bleed: bleed, breakable: false, below: below, inset-bas: inset-bas, above: 0pt)
    if ancre-bas { ancrer-bas(aplat) } else { bloc-plein(corps, fill: fill, bleed: bleed, breakable: false, below: below, inset-bas: inset-bas) }
  }

  // Eventuelles images suivantes (i > 0) — cas marginal non exerce a ce jour
  // (environnement, seul chapitre en stack, n'en porte jamais qu'une), garde
  // pour rester generique.
  for (i, im) in images.enumerate() {
    if i == 0 { continue }
    let bleed-im = im.at("bleed", default: false)
    let avec-legende = not bleed-im
    if bleed-im {
      // Float : reserve sa place dans le flux, donc le chapitre suivant ne
      // chevauche pas ce qui est affiche en bas de page (cf. note plus haut
      // sur le choix de `float: true`). `supprimer-pied()` DANS le contenu
      // flotte, et non juste apres en flux normal : un float peut atterrir
      // sur une page differente de celle ou le flux normal se trouve encore
      // au moment de l'appel — hors du float, le marqueur se retrouverait sur
      // la mauvaise page et le pied de page normal resterait visible la ou le
      // visuel deborde (verifie a l'usage : superposition texte/visuel).
      place(bottom, dy: dy-pied-reel, float: true)[
        #visuel-empile(im, colle: false, legende: false)
        #bande-pied-ouverture(im)
        #supprimer-pied()
      ]
    } else {
      visuel-empile(im, colle: false, legende: avec-legende)
    }
  }
  // Rare (resultats en stack) : le pied de cloture suit simplement les
  // visuels, hors aplat — cas trop marginal pour justifier de l'y inclure.
  if pied != none { pied }
}

// Aiguillage : layout, teinte et debordement viennent des donnees
// (cf. reference_renderer.py — _reshape_chapitres_pdf). `resultats` ferme
// toujours la fiche : son encart porte son propre pied de page (`ligne-pied`)
// et s'ancre en pied de page reelle — le pied de page normal est supprime
// sur cette page pour ne pas le dupliquer.
#let chapitre(ch) = {
  let layout = ch.at("layout", default: "full")
  let label = ch.at("label")
  let texte = ch.at("texte")
  // `sans-image-resultats` : tout dernier repli de la contrainte "2 pages"
  // (cf. render_pdf). Le chapitre bascule alors de lui-meme sur le motif
  // "texte seul" — l'aiguillage plus bas ne retient duo/stack qu'avec au
  // moins un visuel.
  let images = if sans-image-resultats and ch.at("key", default: "") == "resultats" {
    ()
  } else {
    ch.at("images", default: ())
  }
  let fill = if ch.at("fill", default: "grey") == "peach" { c2c-peach } else { c2c-tint }
  let bleed = ch.at("bleed", default: false)
  let cloture = ch.at("key", default: "") == "resultats"
  // Ajustement hauteur image/texte (demande explicite) : reserve aux deux
  // chapitres de recit qui alternent duo/duo-inverse — pas a resultats (deja
  // regle par le bleed + echelle-duo de la boucle de remplissage), pas a
  // environnement (toujours en stack, cf. plus haut).
  let fit-hauteur = ch.at("key", default: "") in ("ergonomie", "visuel")
  // Coupe-circuit de securite (cf. desactiver-ancre-environnement) : lu ICI,
  // et nulle part ailleurs, pour que les deux usages de `ancre_bas` plus bas
  // (chapitre avec visuel empile, chapitre sans visuel) restent synchronises.
  let ancre-bas = ch.at("ancre_bas", default: false) and not desactiver-ancre-environnement

  let construire(pied) = if layout == "colonnes" {
    m-colonnes(label, texte, fill: fill, bleed: bleed, pied: pied)
  } else if layout == "duo" and images.len() > 0 {
    m-duo(label, texte, images.at(0), fill: fill, bleed: bleed, pied: pied, fit-hauteur: fit-hauteur)
  } else if layout == "duo-inverse" and images.len() > 0 {
    m-duo(label, texte, images.at(0), inverse: true, fill: fill, bleed: bleed, pied: pied, fit-hauteur: fit-hauteur)
  } else if layout == "stack" and images.len() > 0 {
    m-stack(label, texte, images, fill: fill, bleed: bleed, pied: pied, ancre-bas: ancre-bas)
  } else if ancre-bas {
    ancrer-bas(m-full(label, texte, fill: fill, bleed: bleed, pied: pied, breakable: false, above: 0pt))
  } else {
    m-full(label, texte, fill: fill, bleed: bleed, pied: pied, breakable: not cloture)
  }

  if cloture {
    // L'aplat (fond teinte) touche le bord bas reel de la page ; son pied de
    // page embarque (ligne-pied), lui, reste a bonne distance de ce bord grace
    // a l'inset bas de bloc-plein (18pt), exactement comme le pied de page
    // normal dans sa propre marge.
    //
    // Ancrage bas par RESSORT et non par `place(bottom, float: true)` : le
    // float reservait dans le flux la hauteur TOTALE de l'encart, y compris
    // les marge-bas-page dont il deborde volontairement dans la marge de
    // pied. Soit ~42pt de place fantome, reclamee au flux sans etre occupee :
    // de quoi faire basculer l'encart en page suivante alors qu'il tenait, et
    // la boucle de verification en concluait qu'il fallait sacrifier son
    // visuel (bug signale : « la boucle a supprime l'image resultats alors
    // qu'il y a clairement la place »).
    //   · `pad(bottom: -marge-bas-page)` retranche exactement ce debord de la
    //     hauteur mise en page : l'encart n'occupe plus dans le flux que ce
    //     qu'il occupe reellement AU-DESSUS de la marge de pied, et son rendu
    //     descend jusqu'au bord physique comme avant ;
    //   · `v(1fr)` le pousse en bas de page, ce que faisait `place(bottom)`.
    // Aucun risque de chevauchement en retour : ce chapitre ferme toujours la
    // fiche, rien ne le suit jamais (c'est ce risque, et lui seul, qui avait
    // impose `float: true` a l'origine).
    // `v(gap-chapitre)` EXPLICITE avant le ressort, et pas seulement le
    // `above` de l'aplat : une spacing faible (ce qu'est `above`) est
    // ESCAMOTEE par Typst des qu'elle voisine une spacing explicite — le
    // ressort. L'encart se retrouvait donc separe du chapitre precedent par
    // le seul ressort, c'est-a-dire par « ce qui restait sur la page » : un
    // gap arbitraire, souvent bien plus petit que celui qui separe deux
    // chapitres ordinaires (bug signale : « l'espace entre aspects visuels et
    // resultats & impact est beaucoup trop faible »). Pose explicitement, ce
    // gap vaut toujours gap-chapitre, exactement comme entre deux chapitres
    // quelconques — et il suit les paliers de la boucle avec eux, donc
    // l'egalite des espaces inter-chapitres tient a chaque essai. Si la page
    // ne peut plus l'offrir, l'encart bascule et la boucle resserre les
    // marges internes de ce chapitre (cf. MARGE_RESULTATS_LADDER) : c'est
    // bien le padding qui cede, jamais le gap.
    //
    // GARDE-FOU : ce traitement (bloc NON coupable, ancre par ressort,
    // debordant dans la marge de pied) suppose implicitement que le pave de
    // cloture tient sur UNE page, si besoin une page fraiche entiere. Une
    // redaction de « Resultats & impact » inhabituellement longue (fiche
    // dense, cf. catalogue cartes.gouv) peut produire un pave plus haut que
    // cette page entiere — aucun levier de la boucle de remplissage ne reduit
    // la hauteur du TEXTE de cloture (echelle-duo ne joue que sur la largeur
    // de l'image, marge-resultats que sur les insets). Un bloc non coupable
    // plus haut que la page ne peut alors etre pose nulle part sans deborder,
    // et Typst produit un defaut mesure sur le rendu : pied de page duplique
    // (le pied embarque ET le pied normal, non supprime, apparaissent tous
    // les deux) et pagination incoherente (numero/total fige a une valeur
    // fausse) — bug signale. On mesure donc le pave AVANT de le poser, et on
    // n'engage le traitement ancre/bleed que s'il tient dans une page
    // entiere ; sinon, repli sur un chapitre ordinaire, BREAKABLE, qui
    // s'etale sur autant de pages que necessaire — la seule issue qui ne
    // declenche jamais ce defaut, au prix du visuel de cloture et de la
    // pose « collee au bord reel » dans ce seul cas, rare, de redaction hors
    // gabarit.
    context {
      let pied-cloture = ligne-pied()
      let candidat = construire(pied-cloture)
      let largeur-mesure = if bleed { page-w } else { texte-w }
      let h-candidat = measure(block(width: largeur-mesure)[#candidat]).height
      // Hauteur utile d'une page ORDINAIRE (sans le debord de la marge de
      // pied que permet le traitement ancre/bleed) : borne deliberement
      // conservatrice, elle garantit que le pave tiendra sur une page fraiche
      // meme sans invoquer ce debord.
      let h-max-page = bas-zone-contenu - marge-haut-page
      if h-candidat <= h-max-page {
        v(gap-chapitre)
        v(poids-ressort-cloture * 1fr)
        pad(bottom: -marge-bas-page)[#candidat]
        supprimer-pied()
      } else {
        v(gap-chapitre)
        m-full(label, texte, fill: fill, bleed: true, pied: pied-cloture, breakable: true)
        supprimer-pied()
      }
    }
  } else {
    construire(none)
  }
}

// =====================================================================
// COUVERTURE — elle porte aussi l'index des projets. Rendue seulement pour
// une selection de plusieurs projets (B3 du plan) : pour une fiche projet
// unique, le document commence directement page 1 sur la fiche elle-meme —
// ni logo-texte en grand, ni titre "References projets", ni index.
// =====================================================================
#if index.len() > 0 [
#set page(
  paper: "a4",
  margin: (left: marge-x, right: marge-x, top: 29.8pt, bottom: 60pt),
)

#image(logo-wordmark, width: 320pt)

#v(1fr)

// Bande orange verticale : ancrage du bloc de titre, cote texte a droite.
#grid(
  columns: (4pt, 1fr),
  column-gutter: 16pt,
  rect(fill: c2c-orange, width: 4pt, height: 66pt, stroke: none),
  [
    #set par(justify: false, leading: 0.5em)
    #text(fill: c2c-orange, weight: "black", size: 26pt)[#titre]
    #v(6pt)
    #text(fill: c2c-ink, weight: "bold", size: 16pt)[#sous-titre]
    #if sur-titre != "" [
      #v(3pt)
      #text(fill: c2c-grey, weight: "semibold", size: 11pt)[#sur-titre]
    ]
  ],
)

#{
  v(34pt)
  text(size: 6.5pt, fill: c2c-grey, weight: "bold", tracking: 0.8pt)[#upper("Projets présentés")]
  v(9pt)
  // Index en bandes modulaires : numero orange, intitule, page.
  //
  // Les entrees viennent des DONNEES et non d'un `outline()` : la couverture
  // est compilee seule, sans les projets qu'elle annonce (cf. la note sur
  // l'assemblage, plus haut). Les numeros de page sont ceux du document
  // assemble, connus cote Python une fois chaque projet compose.
  for (i, e) in index.enumerate() {
    let num = if i + 1 < 10 { "0" + str(i + 1) } else { str(i + 1) }
    block(above: 0pt, below: 3pt, breakable: false)[
      #block(fill: c2c-tint, inset: (x: 10pt, y: 8pt), width: 100%)[
        #grid(
          columns: (24pt, 1fr, auto),
          column-gutter: 10pt,
          align: (left + horizon, left + horizon, right + horizon),
          text(fill: c2c-orange, weight: "black", size: 11pt)[#num],
          text(size: 10pt, weight: "semibold")[#e.at("titre")],
          text(size: 9pt, fill: c2c-grey, weight: "semibold")[#e.at("page")],
        )
      ]
    ]
  }
}

#v(1fr)
]

// =====================================================================
// PAGES INTERIEURES
// =====================================================================
#set page(
  paper: "a4",
  // Marge haute reduite (85pt a l'origine) : le titre (ou, sur les pages de
  // suite, le rappel de projet + icone) peut venir bien plus pres du haut de
  // page sans probleme — economie d'espace demandee explicitement.
  margin: (left: marge-x, right: marge-x, top: marge-haut-page, bottom: marge-bas-page),
  header: running-header,
  footer: running-footer,
  // Calcule (pas 71% fixe) pour que le blanc AU-DESSUS du pied de page
  // egale gap-standard — meme espace qu'entre l'image libre et le chapitre
  // suivant (demande explicite). Une valeur fixe ne suit pas marge-bas-page
  // quand celle-ci change (cf. sa propre note) ; ce calcul, si.
  footer-descent: (gap-standard / marge-bas-page) * 100%,
  background: place(top, rect(width: 100%, height: 7pt, fill: c2c-orange, stroke: none)),
)

// Le fragment ne commence pas forcement page 1 du document assemble.
#counter(page).update(page-offset + 1)

#for (i, p) in projets.enumerate() {
  // La toute premiere iteration ne doit PAS sauter de page — sinon la premiere
  // page du fragment reste blanche. Les suivantes, s'il y en a (compilation
  // autonome d'un fichier multi-projets), ouvrent bien une page neuve.
  if i > 0 { pagebreak() }

  // `numero` = position REELLE dans le lot (cf. reference_renderer.py) : chaque
  // projet est compile seul, `i` vaut donc toujours 0 pour un lot de plusieurs
  // projets sans cette cle — tous affichaient "01" (bug signale).
  let n-affiche = p.at("numero", default: i + 1)
  let num = if n-affiche < 10 { "0" + str(n-affiche) } else { str(n-affiche) }
  let client = p.at("client", default: "")
  let design = p.at("designation", default: "")
  let blocs = p.at("blocs", default: ())

  // Ancre d'index / de signet, sans rendu propre (cf. show rule).
  heading(level: 1)[#if client != "" and design != "" [#client — #design] else [#client#design]]

  // --- Identite du projet : gros numero + client + designation ---------
  // `stack` et non un enchainement de #text : le retour a la ligne du balisage
  // insererait une espace en debut de seconde ligne. L'icone C2C (autrefois
  // dans l'entete de page, desalignee de cette ligne) est integree ICI, dans
  // la meme grille : c'est le seul moyen de la rendre reellement sur la meme
  // ligne que le titre (mesure sur le rendu).
  block(above: 0pt, below: gap-titre, breakable: false)[
    #grid(
      columns: (auto, 1fr, auto),
      column-gutter: 14pt,
      align: (top, top, horizon),
      text(fill: c2c-orange, weight: "black", size: 34pt)[#num],
      {
        set par(justify: false, leading: 0.45em)
        if design != "" {
          stack(
            dir: ttb,
            spacing: 5pt,
            text(weight: "black", size: 19pt)[#client],
            text(fill: c2c-orange, weight: "semibold", size: 12pt)[#design],
          )
        } else {
          text(weight: "black", size: 19pt)[#client]
        }
      },
      box(width: 18.75pt, height: 17.25pt)[#image(logo-icon, width: 18.75pt)],
    )
  ]

  // --- Faits, en cellules modulaires ----------------------------------
  let equipe = p.at("equipe", default: ())
  // Le budget est un fait de projet au meme titre que le client, la periode ou
  // le secteur — pas une donnee de recit noyee dans « Environnement » : il a
  // donc sa cellule, entre le client (et sa sous-entite) et la periode.
  // Le libelle complet (montant + unite) est compose cote Python, jamais ici
  // (cf. reference_renderer._budget_label).
  let cells = (
    ("Client",      client),
    ("Sous-entité", p.at("sous_entite", default: "")),
    ("Budget",      p.at("budget", default: "")),
    ("Période",     p.at("periode", default: "")),
    ("Secteur",     p.at("secteur", default: "")),
  ).filter(c => c.at(1) != none and c.at(1) != "")
  if cells.len() > 0 {
    // `below: gap-cellules` : Typst retient le PLUS GRAND des deux espaces
    // adjacents — laisser l'espacement de bloc par defaut ici (1.2em)
    // l'emporterait sur le gap-cellules demande par le bloc suivant.
    block(below: gap-cellules)[#faits(cells)]
  }

  // --- Seconde ligne des elements cles : contacts / projet publie -------
  // Les contacts et le lien de publication sont des FAITS de projet, comme le
  // client ou la periode : ils prolongent la rangee ci-dessus (memes cellules,
  // cf. cellule-fait) au lieu d'ouvrir un bloc a eux, et se posent AVANT la
  // rangee de qualification (competences / equipe), qui reste la derniere du
  // pave d'entete.
  //
  // Deux colonnes egales quand les deux sont renseignes. Un seul des deux :
  // sa cellule prend toute la mesure de texte, jamais une demi-largeur suivie
  // d'un blanc (demande explicite — « s'il n'y a pas de liens vers le projet,
  // la ligne contact occupe toute la largeur pour ne pas laisser d'espace
  // blanc »). Les colonnes sont posees en `1fr` et non en `demi` : c'est ce
  // qui permet a la meme grille de servir les deux cas.
  let contacts = p.at("contacts", default: ())
  let lien = p.at("lien_projet", default: "")
  let lien-label = p.at("lien_projet_label", default: lien)
  let cellules-cles = ()
  if contacts.len() > 0 {
    cellules-cles.push(cellule-fait("Contacts", corps-contacts(contacts)))
  }
  if lien != "" {
    cellules-cles.push(cellule-fait("Projet publié", corps-lien(lien, lien-label)))
  }
  if cellules-cles.len() > 0 {
    // `above` ET `below` a gap-cellules : Typst retient le plus grand des deux
    // espaces adjacents, la rangee reste donc a la meme distance de la rangee
    // de faits au-dessus et de la qualification en dessous — un seul blanc de
    // grille, comme entre deux cellules voisines.
    block(above: gap-cellules, below: gap-cellules, breakable: false)[
      // `context` : la largeur de la colonne « Contacts » est MESUREE sur son
      // contenu (cf. largeur-contacts) — une demi-mesure figee coupait en deux
      // lignes un contact qui n'avait besoin que de 2.6pt de plus.
      #context grid(
        // Deux cellules <=> contacts ET lien renseignes : la colonne mesuree
        // n'a donc pas d'autre cas a couvrir. Seule, une cellule prend toute
        // la mesure de texte.
        columns: if cellules-cles.len() == 1 { (1fr,) }
                 else { (largeur-contacts(contacts), 1fr) },
        column-gutter: gap-cellules,
        ..cellules-cles,
      )
    ]
  }

  // --- Competences et equipe en vis-a-vis ------------------------------
  // Juste sous les faits, avant le recit : ce sont des donnees de
  // qualification (que sait-on faire, avec qui), pas de la narration.
  // Deux blocs de nature differente : les mettre cote a cote evite deux
  // bandes pleine largeur empilees, qui rigidifieraient le haut de la fiche.
  // Chacun est une rangee de modules qui se replie d'elle-meme (cf. modules) :
  // la hauteur du bloc suit le contenu, elle n'est plus dictee par une grille.
  //
  // ESPACEMENT (cf. gap-qualification) : cette rangee se detache des cellules
  // de faits, au-dessus, ET du chapeau, en dessous. Elle etait auparavant a
  // gap-cellules des deux cotes, pour se lire comme un element de plus de la
  // grille des faits — mais depuis que cette grille compte deux rangees
  // (faits, puis contacts / projet publie), la qualification s'y noyait, et
  // un chapeau reduit par la boucle venait se coller dessous (bug signale sur
  // la fiche Rennes). Elle porte un autre motif que les cellules (micro-
  // entete + modules, et non un aplat de valeur) : elle a droit a son propre
  // blanc.
  let competences = p.at("competences", default: ())
  let bloc-competences = if competences.len() > 0 {
    [
      #micro-entete("Compétences & technologies")
      #modules(competences)
    ]
  }
  let bloc-equipe = if equipe.len() > 0 {
    [
      #micro-entete("Équipe Camptocamp")
      #modules-equipe(equipe)
    ]
  }

  if competences.len() > 0 and equipe.len() > 0 {
    block(above: gap-qualification, below: gap-qualification, breakable: false)[
      #grid(
        columns: (demi, demi),
        column-gutter: gouttiere,
        align: (top, top),
        bloc-competences,
        bloc-equipe,
      )
    ]
  } else if competences.len() > 0 {
    // Seul, un bloc prend toute la mesure de texte : les modules s'y replient
    // sur d'autant moins de lignes.
    block(above: gap-qualification, below: gap-qualification, breakable: false)[#bloc-competences]
  } else if equipe.len() > 0 {
    block(above: gap-qualification, below: gap-qualification, breakable: false)[#bloc-equipe]
  }

  // --- Chapeau : un chapitre a part entiere, aplat gris compris ----------
  // Il ne se distingue plus des autres chapitres par son habillage (il fut
  // successivement un titre/corps a lui, puis un titre/corps iso mais sur
  // blanc) : meme motif, meme aplat, meme largeur — seule sa POSITION le
  // designe comme chapeau.
  //
  // Quand l'image libre est "promue" en tete de fiche (equipe non renseignee,
  // cf. reference_renderer._reshape_chapitres_pdf, fanion `sous_contexte`),
  // elle ne s'insere pas dans le flux des chapitres : elle est consommee ICI,
  // avec le chapeau, qui vient se poser DESSUS (cf. chapeau-sur-image).
  let contexte = p.at("contexte", default: "")
  let sous-contexte = bl => bl.at("sous_contexte", default: false)
  // `masquer-image-libre` (dernier repli de la sequence d'« Environnement »,
  // cf. le lexique des leviers plus haut) : l'image promue est retiree, comme
  // si la fiche n'en portait pas — le chapeau (s'il est redige) retombe sur
  // son motif "texte seul" ordinaire (cf. plus bas).
  let image-chapeau = if masquer-image-libre { none } else { blocs.find(sous-contexte) }
  let blocs = blocs.filter(bl => not sous-contexte(bl))

  // Fiche « ouverture aeree » : l'image libre ferme la page 1 et les chapitres
  // commencent tous page 2 (cf. image-libre-ouverture). Le chapeau prend alors
  // le MEME blanc que celui qui entoure le bloc de titre — demande explicite :
  // « reutiliser l'espace utilise pour titre pour separer ce bloc elements
  // cles et le premier bloc texte ». Ailleurs il reste colle a la grille des
  // faits, dont il n'est qu'un element de plus.
  let ouverture-aeree = blocs.any(bl => bl.at("ouverture_aeree", default: false))
  let gap-chapeau = if ouverture-aeree { gap-titre } else { gap-cellules }
  // `below: 0pt` en ouverture aeree : le blanc sous le contexte n'appartient
  // plus au chapeau, il fait partie de l'espace que le pave centre se partage
  // (demande explicite : l'image se repartit dans « l'espace qui reste entre ce
  // bloc texte et le pied de page »). Les 6pt d'espacement de bloc habituels
  // s'ajoutaient sinon AU-DESSUS de l'image seulement, et la decentraient
  // d'autant — mesure sur le rendu : 95.7pt de blanc en haut contre 87.4 en bas.
  let below-chapeau = if ouverture-aeree { 0pt } else { 6pt }

  if contexte != "" and image-chapeau != none {
    chapeau-sur-image("Contexte complet du projet", contexte, image-chapeau)
  } else if contexte != "" {
    // Exactement le motif "texte seul" des chapitres (m-full) : meme aplat
    // gris, memes paddings, meme style de titre, meme corps — et donc la
    // meme largeur que la rangee de faits, dont il prolonge la grille.
    m-full("Contexte complet du projet", contexte, above: gap-chapeau, below: below-chapeau)
  } else if image-chapeau != none {
    // Pas de chapeau redige : l'image promue se pose seule, dans le flux.
    image-libre(image-chapeau)
  }

  // Plus de visuel d'ouverture pleine largeur (supprime pour economiser une
  // page) : Environnement enchaine directement apres le contexte, sur la
  // meme page si la place le permet.

  // --- Chapitres et image libre : chacun sur sa mise en page -----------
  // Un seul flux ordonne (cf. reference_renderer._reshape_chapitres_pdf) :
  // au plus une image "libre" s'y intercale, a la place du premier chapitre-
  // image absent — plus de galerie de visuels restants en fin de page (le
  // rattachement d'image est desormais explicite, un-pour-un, jamais un pool).
  for bl in blocs {
    if bl.at("type", default: "chapitre") == "image_libre" {
      if bl.at("ouverture_aeree", default: false) {
        image-libre-ouverture(bl)
      } else {
        image-libre(bl)
      }
    } else if bl.at("texte", default: "") != "" {
      chapitre(bl)
    }
  }
}
