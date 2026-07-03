// =====================================================================
// Gabarit CV Camptocamp — mise en page figee pour appels d'offre
// Charte : Messina Sans · orange #FF680A · gris #7A7F82 · fond blanc
//          angles droits · sentence case · alignement gauche
//
// DESTINATION : diffusion numerique uniquement.
// Format 1 page strict — gere par build-cv.py (reduction automatique).
// =====================================================================

// --- Jetons de marque -----------------------------------------------
#let c2c-orange = rgb("#FF680A")
#let c2c-orange-dark  = c2c-orange.darken(28%)
#let c2c-orange-light = c2c-orange.lighten(86%)
#let c2c-grey-light = rgb("#EEEFEF")
#let c2c-grey   = rgb("#7A7F82")
#let c2c-ink    = rgb("#1A1A1A")
#let c2c-title  = c2c-grey.darken(45%)   // gris fonce : nom + titres de projet
#let c2c-font   = "Messina Sans"

// --- Donnees ---------------------------------------------------------
#let data-path = sys.inputs.at("data", default: "data/exemple.yaml")
#let cv = yaml(data-path)
#let id = cv.at("identite")
#let font_reduction_val = cv.at("font_reduction", default: 0) * 0.5pt

// --- Document --------------------------------------------------------
#set document(
  title: id.at("prenom") + " " + id.at("nom") + " — CV Camptocamp",
  author: "Camptocamp SA",
)
#set text(font: c2c-font, size: 8.5pt - font_reduction_val, fill: c2c-ink, lang: "fr")
#show link: it => text(fill: c2c-ink)[#it.body]  // neutralise la coloration automatique des URLs
#set par(justify: false, leading: 0.55em, spacing: 0.65em)

// --- Page : ecran, pas d'impression ---------------------------------
#set page(
  paper: "a4",
  margin: 28pt,
)

// --- Listes a puce --------------------------------------------------
#set list(
  indent: 3pt,
  body-indent: 5pt,
  spacing: 0.45em,
  marker: text(fill: c2c-orange, size: 10pt - font_reduction_val)[›],
)

// --- Composants -----------------------------------------------------
#let rule-thin = line(length: 100%, stroke: 0.5pt + c2c-grey.lighten(45%))

// Titre de section : orange, soulignement court
#let section(title) = {
  block(breakable: false, above: 15pt, below: 9pt)[
    #stack(
      dir: ttb,
      spacing: 5pt,
      text(fill: c2c-orange, weight: "black", size: 10pt - font_reduction_val)[#title],
      line(length: 20pt, stroke: 2pt + c2c-orange),
    )
  ]
}

// =====================================================================
// EN-TETE — logo / identite
// =====================================================================
#grid(
  columns: (auto, 1fr),
  column-gutter: 20pt,
  align: horizon,
  image("assets/C2C_2022_RGB_square_logo.svg", height: 40pt),
  [
    #text(weight: "black", size: 22pt - font_reduction_val, fill: c2c-title)[#id.at("prenom") #id.at("nom")]
    #v(-2pt)
    #text(weight: "semibold", size: 12pt - font_reduction_val, fill: c2c-orange)[#id.at("poste")]#if id.at("departement", default: "") not in (none, "") [
      #h(6pt)#text(size: 9pt - font_reduction_val, fill: c2c-grey, weight: "regular")[· #id.at("departement")]
    ]
  ],
)

// separateur gris entre l'en-tete et le premier bloc
#v(7pt)
#rule-thin
#v(8pt)

// =====================================================================
// PROFIL — le titre englobe le paragraphe ET le bloc elements cles.
//   ligne 1 : titre "Profil"
//   ligne 2 : deux colonnes  [ paragraphe ] [ elements cles (orange) ]
// =====================================================================
#let langues = id.at("langues", default: ())
#let langues-str = if langues.len() > 0 {
  langues.map(l => l.at("langue") + " " + l.at("niveau")).join("  ·  ")
} else { "" }

// titre (libelle) en graisse light, valeur (item) en graisse bold
#let info-row(label, value) = {
  if value != none and value != "" {
    block(below: 5pt)[
      #text(weight: "light", size: 8pt - font_reduction_val)[#label : ]#text(weight: "bold", size: 8pt - font_reduction_val)[#value]
    ]
  } else { none }
}

#section("Profil")
#grid(
  columns: (1fr, 36%),
  column-gutter: 16pt,
  align: (top + left, top + left),
  // colonne gauche : paragraphe profil
  grid.cell(inset: 0pt)[
    #if cv.at("profil", default: none) != none [
      #text(size: 8.5pt - font_reduction_val)[#cv.at("profil")]
    ]
  ],
  // colonne droite : cellule orange pleine hauteur, elements cles empiles
  grid.cell(fill: c2c-orange, inset: (x: 9pt, y: 7pt))[
    #set text(fill: white)
    #info-row("Expérience", str(id.at("experience_ans")) + " ans")
    #info-row("Localisation", id.at("localisation", default: none))
    #info-row("Langues", langues-str)
  ],
)

// =====================================================================
// COMPETENCES CLES — 2 catégories par ligne, compact (gris clair)
// =====================================================================
#let competences = cv.at("competences", default: ())
#if competences.len() > 0 {
  section("Compétences clés")

  let comp-label-w = 88pt   // largeur colonne libellé catégorie
  let comp-gap     = 2pt    // espace vertical entre les lignes
  let comp-row-inset = (x: 7pt, y: 3pt)
  let comp-items-size = (cv.at("comp_items_font", default: 7.5) - cv.at("font_reduction", default: 0) * 0.5) * 1pt

  // Contenu d'une cellule catégorie : libellé orange + items
  let comp-cell(c) = grid(
    columns: (comp-label-w, 1fr),
    align: (top + left, top + left),
    column-gutter: 5pt,
    text(size: 7pt - font_reduction_val, fill: c2c-orange, weight: "bold")[#c.at("categorie")],
    text(size: comp-items-size, fill: c2c-ink)[#c.at("items").join("  ·  ")],
  )

  // Toujours 2 catégories côte à côte ; dernière seule si nombre impair.
  let rows = ()
  let i = 0
  while i < competences.len() {
    if i + 1 < competences.len() {
      rows.push(
        block(breakable: false, spacing: 0pt)[
          #grid(
            columns: (1fr, 1fr),
            column-gutter: 0pt,
            inset: comp-row-inset,
            fill: c2c-grey-light,
            grid.vline(x: 1, stroke: 0.5pt + c2c-grey.lighten(45%)),
            comp-cell(competences.at(i)),
            comp-cell(competences.at(i + 1)),
          )
        ]
      )
      i += 2
    } else {
      rows.push(
        block(
          fill: c2c-grey-light,
          inset: comp-row-inset,
          width: 100%,
          spacing: 0pt,
          breakable: false,
        )[#comp-cell(competences.at(i))]
      )
      i += 1
    }
  }
  rows.join(v(comp-gap))
}

// =====================================================================
// CERTIFICATIONS & FORMATIONS
// =====================================================================
#let certs = cv.at("certifications", default: ())
#if certs.len() > 0 {
  section("Certifications & formations")
  for c in certs [
    - #text(weight: "semibold", size: 8.5pt - font_reduction_val)[#c.at("intitule")]
      #text(fill: c2c-grey, size: 8.5pt - font_reduction_val)[— #c.at("organisme")#if c.at("annee", default: none) != none [, #str(c.at("annee"))]]
  ]
}

// =====================================================================
// PROJETS DE REFERENCE
// =====================================================================
#let projets = cv.at("projets", default: ())
#if projets.len() > 0 {
  section("Projets de référence")
  for (i, p) in projets.enumerate() {
    let periode = p.at("periode", default: "")
    let role    = p.at("role", default: "")
    let reals   = p.at("realisations", default: ())
    let techs   = p.at("technologies", default: ())
    // marge haute accrue pour distinguer chaque projet (et du titre de section)
    block(breakable: false, above: if i == 0 { 6pt } else { 15pt })[
      // titre du projet + date/fonction sur la meme ligne (orange fonce, sans fond)
      #grid(
        columns: (1fr, auto),
        column-gutter: 10pt,
        align: (bottom + left, bottom + right),
        text(weight: "bold", size: 9.5pt - font_reduction_val, fill: c2c-title)[#p.at("client", default: "")],
        text(fill: c2c-orange-dark, size: 8pt - font_reduction_val, weight: "semibold")[#periode#if periode != "" and role != "" [#h(6pt)·#h(6pt)]#role],
      )
      #if p.at("contexte", default: none) != none [
        #v(2pt)
        #text(size: 8.5pt - font_reduction_val)[#p.at("contexte")]
      ]
      #if reals.len() > 0 or techs.len() > 0 {
        // colonne gauche : realisations (liste a puces)
        let col-gauche = {
          for r in reals [- #text(size: 8.5pt - font_reduction_val)[#r]]
        }
        // colonne droite : technologies en liste
        // Si > 5 items, affichage sur 2 sous-colonnes pour ne pas dépasser
        // la hauteur du bloc réalisations (3 puces) en face.
        let col-droite = {
          if techs.len() > 0 {
            text(size: 7pt - font_reduction_val, fill: c2c-grey, weight: "bold")[Tech]
            v(1pt)
            if techs.len() > 5 {
              let mid = calc.ceil(techs.len() / 2)
              let half1 = techs.slice(0, count: mid)
              let half2 = techs.slice(mid)
              grid(
                columns: (1fr, 1fr),
                column-gutter: 4pt,
                align: (top + left, top + left),
                {
                  set list(marker: text(fill: c2c-grey, size: 8pt)[·], indent: 0pt, body-indent: 4pt, spacing: 0.32em)
                  for t in half1 [- #text(size: 7.5pt - font_reduction_val, fill: c2c-ink)[#t]]
                },
                {
                  set list(marker: text(fill: c2c-grey, size: 8pt)[·], indent: 0pt, body-indent: 4pt, spacing: 0.32em)
                  for t in half2 [- #text(size: 7.5pt - font_reduction_val, fill: c2c-ink)[#t]]
                },
              )
            } else {
              set list(
                marker: text(fill: c2c-grey, size: 8pt)[·],
                indent: 0pt, body-indent: 4pt, spacing: 0.32em,
              )
              for t in techs [- #text(size: 7.5pt - font_reduction_val, fill: c2c-ink)[#t]]
            }
          }
        }
        v(3pt)
        // bloc double-colonne en gris clair, separateur vertical + padding pour respirer
        block(fill: c2c-grey-light, inset: (x: 8pt, y: 6pt), width: 100%)[
          #if techs.len() > 0 {
            grid(
              columns: (1fr, 34%),
              column-gutter: 12pt,
              align: (top + left, top + left),
              grid.vline(x: 1, stroke: 0.6pt + c2c-grey.lighten(30%)),
              pad(right: 6pt, col-gauche),
              pad(left: 12pt, col-droite),
            )
          } else {
            col-gauche
          }
        ]
      }
    ]
  }
}

// =====================================================================
// PARCOURS PROFESSIONNEL
// =====================================================================
#let parcours = cv.at("parcours", default: ())
#if parcours.len() > 0 {
  section("Parcours professionnel")
  // Colonne date à 130pt (couvre "Septembre 2006 – Décembre 2009" sans retour à la ligne).
  // Séparateur fin entre chaque entrée : texte · padding 3pt · trait gris · espace 4pt.
  let date-col-w = 100pt  // format MM/YYYY — 130pt n'est plus nécessaire
  for (i, e) in parcours.enumerate() {
    // block(spacing: 0pt) supprime l'espacement par défaut du grid isolé
    block(spacing: 0pt)[
      #grid(
        columns: (date-col-w, 1fr),
        column-gutter: 10pt,
        align: (top + left, top + left),
        text(fill: c2c-grey, size: 8pt - font_reduction_val, weight: "semibold")[#e.at("periode")],
        // Poste à gauche, organisation justifiée à droite
        grid(
          columns: (1fr, auto),
          column-gutter: 8pt,
          align: (left + top, right + top),
          text(size: 8.5pt - font_reduction_val, weight: "semibold")[#e.at("poste")],
          if e.at("employeur", default: "") != "" [
            #text(size: 8pt - font_reduction_val, fill: c2c-grey)[#e.at("employeur")]
          ] else [],
        ),
      )
    ]
    if i < parcours.len() - 1 {
      v(2pt)      // padding 0.5 (ratio 0.5 : 1)
      rule-thin
      v(4pt)      // espace interligne 1
    }
  }
}
