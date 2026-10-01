# Transferência de arquivos por UDP

Trabalho 1 de Redes de Computadores. O projeto usa Python e sockets UDP diretamente para transferir arquivos entre um servidor e clientes. A aplicação implementa confirmação de recebimento, verificação de integridade e retransmissão de blocos.

Os arquivos são tratados como bytes, então podem ser PDFs, imagens, vídeos ou qualquer outro formato.

## Requisitos

- Python 3.10 ou superior. Testado com Python 3.11.9 no Windows.
- Apenas a biblioteca padrão do Python, sem dependências externas.
- Uma porta UDP entre 1025 e 65535. O padrão é 5000.

Execute os comandos abaixo na raiz do projeto. Se estiver usando um ambiente virtual, ative-o antes.

## Como executar

Crie a pasta `shared_files`, caso ela ainda não exista, e coloque nela os arquivos que deseja compartilhar. Inicie o servidor em um terminal:

```shell
python -m server --host 127.0.0.1 --port 5000
```

Em outro terminal, solicite um arquivo que esteja nessa pasta. Substitua `arquivo.pdf` pelo nome desejado:

```shell
python -m client "arquivo.pdf" --host 127.0.0.1 --port 5000
```

O cliente salva o arquivo em `downloads`. Ele não sobrescreve arquivos existentes. Para repetir um download, use outra pasta com `--output-dir`.

O servidor aceita `--shared-dir` para mudar a pasta compartilhada. Ambos aceitam `--timeout`, em segundos, com padrão de 1 segundo. Use o mesmo valor nos dois programas, pois o timeout não é negociado pelo protocolo. Consulte todas as opções com `python -m server --help` e `python -m client --help`.

Para usar computadores diferentes, inicie o servidor com `--host 0.0.0.0` e informe no cliente o IPv4 real da máquina do servidor. A porta escolhida precisa estar acessível pela rede. `127.0.0.1` funciona apenas na própria máquina.

Use `Ctrl+C` para encerrar o cliente ou o servidor.

## Simulação de perda

Com o servidor ativo, execute:

```shell
python -m client "arquivo.pdf" --drop-blocks 3 7 --output-dir downloads/perda
```

O cliente descarta a primeira chegada dos blocos 3 e 7 e não envia seus ACKs. O terminal informa os descartes. O servidor detecta o timeout e retransmite cada bloco, que passa a ser aceito pelo cliente. Escolha um arquivo com pelo menos sete blocos para observar os dois descartes.

O progresso aparece em intervalos de aproximadamente 10%, além do primeiro e do último bloco. Descartes e retransmissões aparecem sempre.

## Dois clientes simultâneos

Coloque dois arquivos diferentes na pasta compartilhada. Com o servidor ativo, execute cada comando em um terminal separado, iniciando o segundo antes de o primeiro terminar:

```shell
python -m client "arquivo1.pdf" --output-dir downloads/cliente1 --drop-blocks 3 7
```

```shell
python -m client "arquivo2.pdf" --output-dir downloads/cliente2
```

Use arquivos grandes para acompanhar as duas transferências. O servidor mantém uma thread e uma fila de mensagens por transferência. O IP, a porta do cliente e o identificador da transferência separam os pedidos e seus ACKs.

## Como o protocolo funciona

O envio usa **stop-and-wait**: o servidor envia um bloco e espera seu ACK antes de enviar o próximo. Isso mantém a implementação simples e limita a um bloco pendente por transferência.

Cada mensagem tem um cabeçalho de 13 bytes, com campos inteiros sem sinal em ordem de bytes de rede (big-endian):

| Campo | Tamanho |
| --- | --- |
| Tipo da mensagem | 1 byte |
| Identificador da transferência | 4 bytes |
| Número de sequência | 4 bytes |
| CRC32 da mensagem | 4 bytes |

O CRC32 é calculado sobre os três primeiros campos e o conteúdo da mensagem, sem incluir o próprio campo de CRC32. O receptor repete o cálculo para detectar corrupção. Também é enviado o CRC32 do arquivo inteiro, usado na validação final.

| Tipo (código) | Sequência | Conteúdo após o cabeçalho |
| --- | --- | --- |
| GET (1) | 0 | Nome do arquivo em UTF-8, relativo à pasta compartilhada |
| META (2) | 0 | Tamanho do arquivo em 8 bytes e CRC32 do arquivo em 4 bytes |
| DATA (3) | 1 até N | Até 1024 bytes do arquivo |
| ACK (4) | Sequência confirmada | Vazio |
| NACK (5) | Bloco solicitado | Vazio |
| FIN (6) | N + 1 | Vazio |
| ERROR (7) | 0 | Código de erro em 1 byte |

Os códigos de erro são: 1 para arquivo inexistente, 2 para acesso proibido, 3 para pedido inválido e 4 para erro de leitura. O cliente traduz esses códigos em mensagens no terminal.

O cliente confirma META com ACK 0 e grava os blocos na ordem de sequência. Blocos já recebidos são confirmados novamente, sem serem gravados duas vezes. Durante a espera por um bloco, pacotes corrompidos ou sequências adiantadas provocam um NACK solicitando o bloco esperado. A ausência de ACK faz o servidor reenviar o pacote após o timeout; isso indica uma possível perda, mas também pode ocorrer por atraso.

O servidor faz no máximo cinco envios de cada META, DATA ou FIN, contando o envio inicial. O cliente também tenta enviar GET até cinco vezes. Durante a transferência, o cliente aguarda até seis vezes seu timeout por bloco ou FIN. Se a recuperação falhar, a transferência termina com erro.

Depois de receber FIN, o cliente confere o tamanho e o CRC32 do arquivo inteiro. Os dados são gravados em um arquivo `.part`, renomeado para o nome final somente após a validação. O cliente confirma FIN e permanece disponível por até cinco vezes seu timeout para repetir essa confirmação, caso o ACK final se perca.

## Tamanho dos pacotes e MTU

Cada bloco contém 1024 bytes de arquivo, exceto o último, que pode ser menor. Com o cabeçalho da aplicação, o payload UDP tem no máximo 1037 bytes. Somando 8 bytes de cabeçalho UDP e 20 bytes de IPv4 sem opções, o pacote IP tem 1065 bytes, abaixo da MTU Ethernet de 1500 bytes. Isso evita fragmentação nesse cenário; redes com MTU menor podem exigir blocos menores. Referências: [UDP](https://www.rfc-editor.org/info/rfc768/), [IPv4](https://datatracker.ietf.org/doc/html/rfc791) e [Ethernet](https://datatracker.ietf.org/doc/html/rfc894).

O `recvfrom` usa um buffer de 65535 bytes, e o protocolo rejeita mensagens maiores que 1037 bytes. O buffer de recepção precisa comportar o datagrama inteiro, mas não precisa ter o mesmo tamanho do bloco enviado.

## Organização e cuidados

- `client/`: argumentos, recebimento, simulação de perda e gravação dos arquivos.
- `server/`: argumentos, atendimento dos clientes, leitura e envio dos arquivos.
- `common/`: socket UDP, mensagens, codificação e CRC32.
- `tests/`: testes unitários e de integração.
- `shared_files/` e `downloads/`: arquivos compartilhados e recebidos.

O servidor rejeita caminhos absolutos, componentes `..` e caminhos resolvidos fora da pasta compartilhada. Arquivos em subpastas são permitidos; no destino, o cliente usa apenas o nome do arquivo.

Não altere um arquivo enquanto ele estiver sendo transferido. Se a verificação final falhar, o cliente informa o erro e descarta o parcial. O projeto usa IPv4 e não retoma downloads interrompidos. Interrupções tratadas, como `Ctrl+C`, removem o `.part`; um encerramento forçado do processo pode deixá-lo na pasta. Nesse caso, remova esse parcial antes de repetir o download, após confirmar que nenhum cliente ainda o está usando.

## Testes

```shell
python -m unittest discover -s tests
```

Os testes incluem transferência real por UDP de arquivo maior que 10 MB, dois clientes simultâneos, perda de dados e ACKs, corrupção, duplicação, erros de arquivo, path traversal e encerramento. Eles usam diretórios temporários. O teste com link simbólico é ignorado quando o sistema não permite criar o link.

## Entrega do trabalho

O enunciado pede um vídeo de até 10 minutos, dividido em duas partes:

1. Demonstrar servidor e cliente com IP e porta, transferência de arquivo maior que 10 MB, perda dos blocos 3 e 7 com timeout e retransmissão, dois clientes baixando arquivos diferentes, erro de arquivo inexistente e bloqueio de path traversal.
2. Exibir o código sem comentários e explicar a criação do socket com `SOCK_DGRAM`, o tamanho dos pacotes e a MTU, a espera pelo ACK e o timeout, o cálculo do CRC32 e a proteção da pasta compartilhada.

Para demonstrar os erros, use `python -m client "inexistente.bin"` e `python -m client "../fora.bin"`, com o servidor ativo e sem um arquivo chamado `inexistente.bin` na pasta compartilhada.

Os pontos principais para a explicação estão em `common/transport.py`, `common/protocol/codec.py`, `server/transfer.py` e `server/file_repository.py`. No servidor, a espera por ACK ocorre em `send_and_wait_for_ack`, pela fila da transferência com `inbox.get(timeout=remaining)`; o recebimento UDP e a distribuição das mensagens ficam no fluxo principal.

A entrega é um ZIP com o código e o link do vídeo no YouTube em comentário particular na atividade do Classroom. Não inclua `.venv`, `.git` ou caches no ZIP.
