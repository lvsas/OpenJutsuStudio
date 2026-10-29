# Component licences

Open Jutsu Studio's application code is [Apache-2.0](../LICENSE). That licence does **not**
relicense model weights, adapters, extensions, source footage or generated-media rights.
Weights are not bundled in this repository. Obtain them through their declared
sources and review the terms for the exact file, variant and intended use.

| Component | Publisher's terms / source |
|---|---|
| LTX 2.x | [Lightricks LTX-2 licence](https://github.com/Lightricks/LTX-2/blob/main/LICENSE) and [licensing page](https://ltx.io/model/license) |
| Ripple adapter | Follow the exact adapter source declared in [the dependency manifest](../dependencies.json), together with its base-model terms. |
| MiniMax H3 and H3 Swap adapter | [MiniMax-H3 model repository](https://huggingface.co/MiniMaxAI/MiniMax-H3); check the Community License's territorial, use and notice conditions. |
| FLUX.2 Klein 9B | [Black Forest Labs licence](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B/blob/main/LICENSE.md); the 9B weights are not covered by the application's Apache-2.0 licence. |
| FLUX 3 Characters and supporting encoders/VAEs | Check the model cards accompanying the exact files in [dependencies](dependencies.md) and the [manifest](../dependencies.json); access may require an upstream agreement. |
| Third-party node packs | Each upstream repository's own licence, linked from the [executor guide](executor-setup.md) and manifest. |
| OpenGenjutsu continuity pack | Its [pack licence](../custom_nodes/opengenjutsu_continuity/LICENSE). |

An adapter's permissive licence does not remove restrictions imposed by its base
model. Community quantisation does not itself grant a different licence. Competition
eligibility, permission to use a model in a territory, commercial use and permission
to redistribute footage are separate questions. This page is a source map, not legal
advice or a claim that every production use is authorised.

See [installation](local-setup.md) for the supported setup boundary and
[the roadmap](../ROADMAP.md) for work not yet delivered.
