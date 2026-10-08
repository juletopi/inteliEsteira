# Cadastro e etiquetas na apresentação

O banco `data/inteliesteira.db` conserva produtos, UFs e vínculos ArUco entre
reinícios. Cada etiqueta usa um ID numérico de `DICT_4X4_250`; o cadastro associa
esse ID ao produto. `PROD-0087` deve estar cadastrado com UF `CE`.

## Preparar as etiquetas e o catálogo

1. Na tela **Produtos**, confirme identificador, UF e atividade de cada produto.
2. Para uma etiqueta já impressa, informe seu **ID antigo** antes de clicar em
   **Baixar ArUco**. Se for uma etiqueta nova, deixe o campo vazio e use o PNG
   ou PDF baixado nessa operação. A coluna **ArUco** mostra o número que ficou salvo.
   Escolha 50, 40, 30 ou 20 mm; para comparar os quatro, selecione a opção de todos
   na mesma folha. Use o PDF em 100% / tamanho real, sem ajustar à página.
   Para reunir os produtos, marque as linhas ou **Marcar todos** e use
   **Baixar selecionados (PDF)**. Cada etiqueta do lote mostra produto, região,
   UF e ID. Se não couber em uma folha, o PDF continua em novas páginas.
3. Imprima as etiquetas finais e teste uma leitura de cada uma pela webcam.
   Confira o produto reconhecido, a UF e a região; `CE` corresponde ao Nordeste.
4. Pare o servidor e salve o catálogo e uma cópia completa do banco:

```powershell
cd F:\inteliEsteira
.\.venv\Scripts\python.exe -m storage.catalog export .\data\catalogo-apresentacao.json
.\.venv\Scripts\python.exe -m storage.catalog verify .\data\catalogo-apresentacao.json --require-aruco
.\.venv\Scripts\python.exe -m storage.catalog backup .\data\inteliesteira-apresentacao.db
```

O catálogo JSON contém os identificadores, UFs, atividade e IDs exatos. O backup
SQLite inclui também o histórico. Leve ambos junto com os PNGs usados na impressão.
O JSON pode ser versionado no Git; o banco continua local. Esses comandos recusam
sobrescrever arquivos existentes: use um novo nome se precisar salvar outra revisão.
Não edite os IDs no catálogo depois de imprimir as etiquetas.

## No computador da apresentação

Se for o mesmo computador/pasta, confira o catálogo salvo antes de iniciar:

```powershell
.\.venv\Scripts\python.exe -m storage.catalog verify .\data\catalogo-apresentacao.json --require-aruco
.\.venv\Scripts\python.exe start.py
```

Se for outra cópia do projeto, copie o JSON para `data/`, instale as dependências
e importe o catálogo com o servidor parado:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m storage.catalog import .\data\catalogo-apresentacao.json
.\.venv\Scripts\python.exe -m storage.catalog verify .\data\catalogo-apresentacao.json --require-aruco
.\.venv\Scripts\python.exe start.py
```

A importação usa os IDs do arquivo, sem sortear ou recalcular números. Um conflito
de ID, UF ou atividade cancela toda a importação e preserva os cadastros locais.
A verificação confere os produtos do catálogo; outros produtos locais podem existir.
Se ela falhar, resolva a divergência antes de usar as etiquetas impressas.

Se excluir produtos na tela, exporte uma nova versão do catálogo. Os registros
marcados como excluídos são levados junto para preservar a reserva dos IDs e aplicar
a exclusão na outra máquina. Eles ficam fora da lista de produtos e da impressão;
o histórico é mantido. Um catálogo antigo não reativa um produto excluído.

O comando `start.py` mantém a configuração de câmera e hardware do ambiente.
Para ler as etiquetas pela webcam, use `CAMERA_MODE=opencv`, como no README.
Teste novamente as etiquetas impressas e a montagem no local: conferir o catálogo
valida o vínculo dos dados, mas não testa foco da câmera, motores ou calibração.

## Recuperar uma etiqueta antiga

Se perdeu o banco, o nome `aruco-PROD-0087-id17.png`, por exemplo, informa o ID 17.
Esse número é apenas um exemplo. Cadastre `PROD-0087`/`CE` e informe o ID real.
Se o nome do arquivo não tiver o número, leia o PNG ou a etiqueta com o detector
ArUco para identificá-lo. Sem o ID ou a etiqueta original, imprima uma nova
etiqueta gerada pelo cadastro atual e salve esse catálogo como referência.
