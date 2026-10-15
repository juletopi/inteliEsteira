# Cadastro e etiquetas na apresentação

Os cadastros ficam em `data/inteliesteira.json`. Cadastrar ou editar produtos,
ativar/desativar, excluir e vincular IDs ArUco atualiza esse arquivo automaticamente.
Na próxima abertura, os mesmos dados são carregados sem importar ou exportar nada.
A bancada padrão e a aplicação principal usam esse arquivo.

## Preparar as etiquetas

1. Na tela **Produtos**, confira identificador, UF e atividade de cada produto.
2. Para uma etiqueta já impressa, informe seu **ID antigo** antes de clicar em
   **Baixar ArUco**. Para uma etiqueta nova, deixe o campo vazio e use o PNG ou
   PDF baixado nessa operação. A coluna **ArUco** mostra o número salvo.
3. Escolha 50, 40, 30 ou 20 mm, ou todos os tamanhos na mesma folha. Imprima o
   PDF em 100% / tamanho real. Para reunir produtos, marque as linhas e use
   **Baixar selecionados (PDF)**. O arquivo continua em novas páginas se necessário.
4. Teste uma leitura de cada etiqueta pela webcam. Confira produto, UF e região.
   O vínculo com o ID é salvo automaticamente no JSON; não é preciso gerar
   outro arquivo de catálogo depois de imprimir.

Excluir um produto grava `"excluido": true` e conserva seu ID reservado. Ele sai
da lista e da impressão; o histórico permanece. Uma versão antiga do arquivo
não reativa produtos excluídos localmente nem troca o ID de etiquetas existentes.

## Abrir no mesmo computador ou em outro

No mesmo computador e pasta, basta iniciar normalmente:

```powershell
.\.venv\Scripts\python.exe start.py
```

Em outra máquina, a cópia do projeto precisa incluir **`data/inteliesteira.json`
atualizado**. Copie a pasta com esse arquivo ou inclua o JSON no commit/push e
atualize a outra máquina antes de iniciar. O salvamento é local; não há
sincronização automática pela internet. Depois de instalar as dependências,
abra normalmente: os cadastros e IDs serão carregados automaticamente.

Para testar sem equipamentos, mantendo esses mesmos cadastros:

```powershell
.\.venv\Scripts\python.exe -m scripts.bancada
```

O painel fica em http://127.0.0.1:5001. Fila e histórico de testes ficam no banco
separado `output/bancada-catalogo.db`. A opção `--demo` usa apenas cadastros TESTE
separados do catálogo principal.

## Histórico e recuperação

O SQLite `data/inteliesteira.db` é criado automaticamente pela aplicação e mantém
fila, histórico e referências dos produtos. Não exige criar um banco manualmente
nem instalar um servidor. O JSON conserva os cadastros, não o histórico completo.
Se precisar transportar também o histórico, faça uma cópia consistente do banco:

```powershell
.\.venv\Scripts\python.exe -m storage.catalog backup .\output\historico-apresentacao.db
```

Use outro nome se esse backup já existir. A gravação automática do JSON usa
substituição atômica; uma falha conserva a alteração no SQLite para recuperação
na próxima abertura. Arquivo inválido ou conflito de etiquetas é informado sem
sobrescrever os dados. Preserve os dois arquivos ao investigar uma divergência.

Se perdeu ambos e tem uma etiqueta antiga, o nome `aruco-PROD-0087-id17.png`,
por exemplo, informa o ID 17. Esse número é apenas um exemplo: cadastre o produto
e informe o ID real da etiqueta. Sem o ID ou a etiqueta original, gere uma nova.

`start.py` mantém a configuração de câmera e hardware do ambiente. Teste foco,
montagem e calibração no local conforme o [roteiro integrado](teste-integrado.md).
