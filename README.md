# Transferência de arquivos sobre UDP

Trabalho 1 de Redes de Computadores, desenvolvido em Python com uso direto
da API de sockets UDP.

## Etapa 1: transporte UDP

O módulo `common/transport.py` envia e recebe datagramas IPv4 usando
`socket.SOCK_DGRAM`, `sendto` e `recvfrom`. Ele preserva os bytes recebidos,
retorna o endereço do remetente e permite configurar o timeout do socket.
O uso com `with` garante o fechamento do socket ao sair do bloco.

O timeout padrão de um segundo é apenas uma configuração inicial do transporte.
Um timeout gera `TimeoutError`; a política de retransmissão será implementada
posteriormente na camada de transferência.

O buffer de recepção de 65.535 bytes permite receber um datagrama IPv4 inteiro.
Esse valor é a capacidade de leitura, não o tamanho dos blocos que enviaremos.
O tamanho dos blocos do protocolo será definido considerando o MTU e os
cabeçalhos IP, UDP e da aplicação.

Cliente e servidor ainda não possuem uma aplicação executável funcional.
Esta etapa não implementa transferência de arquivos, ACKs ou recuperação de
perdas.

## Validação

Requer Python 3.11 ou superior. Os testes usam somente a biblioteca padrão,
com sockets reais na interface local `127.0.0.1`.

Na raiz do projeto, usando o ambiente virtual no PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Para executar um teste individual:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.integration.test_transport.UdpTransportTests.test_exchanges_binary_data_in_both_directions -v
```

Os testes verificam troca de bytes nos dois sentidos, limites entre datagramas,
datagramas vazios, identificação de dois clientes, timeout, interoperabilidade
com um socket UDP simples e fechamento do socket.

Nos testes, a porta `0` solicita ao sistema operacional uma porta disponível,
evitando depender de uma porta fixa. A futura configuração do servidor deverá
exigir uma porta maior que 1024, conforme o enunciado.

## Próximas etapas

1. Definir e testar os formatos de mensagem, serialização e checksum.
2. Implementar os pontos de entrada e uma troca básica entre cliente e servidor.
3. Implementar transferência de arquivos com ACK, timeout e retransmissão.
4. Validar perdas simuladas, duas transferências simultâneas e segurança de caminhos.
