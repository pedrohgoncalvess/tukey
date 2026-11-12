# Identidade visual Tukey

Uma interface de relatório: papel claro, tinta escura, cores de terra, títulos
serifados e números monoespaçados. A hierarquia vem de tipografia, espaço e linhas
de separação. Superfícies são planas, bordas discretas e controles quase retos.

## Fonte dos tokens

`src/tukey/design.tokens.json` é a fonte única. Cada token contém `$type` e
`$value`, organizado em grupos: `color`, `font`, `size`, `space`, `layout`,
`border` e `number`. Dimensões têm valor e unidade; famílias tipográficas são
listas de fontes locais.

`src/tukey/design.py` converte esses valores em propriedades CSS com o prefixo
`--tukey-`. O HTML incorpora esse CSS durante a geração e o SVG lê as mesmas
propriedades, mantendo a identidade em todas as partes do relatório.

```sh
make tokens
```

O comando exporta `docs/design-tokens.css`, pronto para usar em outra interface:

```html
<link rel="stylesheet" href="design-tokens.css">
```

```css
body {
  color: var(--tukey-color-ink);
  background: var(--tukey-color-background);
  font: var(--tukey-size-body)/var(--tukey-number-line-height) var(--tukey-font-body);
}

h1 {
  font-family: var(--tukey-font-heading);
  font-size: var(--tukey-size-title);
}

.panel {
  padding: var(--tukey-space-xl);
  background: var(--tukey-color-surface);
  border: var(--tukey-border-width) solid var(--tukey-color-rule);
  border-radius: var(--tukey-border-radius);
}
```

Edite o JSON e execute `make tokens` novamente para atualizar o CSS exportado.
Novos relatórios HTML usam os tokens atualizados automaticamente. Relatórios já
gerados precisam ser recriados com `tukey PATH --html ARQUIVO`.

## Cores e uso

| Token (`--tukey-color-…`) | Valor | Uso |
| --- | --- | --- |
| `background` | `#f4f0e6` | Papel da página |
| `surface` | `#eae4d7` | Superfície de apoio |
| `canvas` | `#faf7f0` | Área de desenho e campos |
| `ink` | `#2d2923` | Texto principal |
| `muted` | `#635c51` | Texto secundário |
| `rule` | `#cdc3b1` | Separadores |
| `rule-strong` | `#8b806f` | Bordas de controles |
| `accent` | `#73462d` | Links e identificação |
| `module` | `#5b6d74` | Quadrados de módulos |
| `function` | `#74774c` | Círculos de funções |
| `method` | `#9a654b` | Losangos de métodos |
| `import` | `#51666d` | Conexões contínuas de imports |
| `call` | `#84513b` | Conexões pontilhadas de chamadas |
| `contains` | `#a99e88` | Conexões tracejadas de pertencimento |
| `danger` | `#8a3028` | Contorno de alta complexidade em funções |
| `focus` | `#302a21` | Foco e seleção |

## Regras para futuras interfaces

- Preserve fundos planos e a paleta de papel e tinta.
- Use Georgia para títulos, Arial para leitura e Courier para números e código.
- Use a escala de espaço dos tokens para margens e preenchimentos.
- Aplique cor para indicar uma função ou categoria, com texto ou forma de apoio.
- Mantenha foco visível, sublinhado nos links e formatos distintos no grafo.
- Prefira tabelas e separadores simples para apresentar dados.
- Evite gradientes, brilho, sombras decorativas, cápsulas e animações ornamentais.
