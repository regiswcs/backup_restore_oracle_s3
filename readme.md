# Oracle Backup para AWS S3

Este projeto consiste em um script Python para automatizar o processo de backup de um banco de dados Oracle e fazer o upload dos arquivos de backup para um bucket na AWS S3.

## 1. Fluxo Geral da Solução

O fluxo de trabalho automatizado é o seguinte:

1.  **Orquestração por Cron:** O agendador de tarefas (Cron no Linux) invoca o script Python (`backup_oracle_s3.py`) diariamente, passando um parâmetro para definir se o backup será `FULL` ou `INCREMENTAL`.
2.  **Execução do Backup RMAN:** O script Python, utilizando o módulo `subprocess`, executa o comando `rman`. Ele se conecta ao banco de dados Oracle usando a autenticação do sistema operacional (`TARGET /`).
3.  **Geração dos Arquivos:** O RMAN realiza o backup do banco de dados e dos logs arquivados, gerando os arquivos de backup (`backup pieces`) em um diretório temporário local.
4.  **Gerenciamento de Logs:** Após o backup dos logs, o RMAN apaga da área local os logs arquivados que já têm mais de 24 horas, otimizando o espaço em disco e mantendo uma cópia local recente para emergências.
5.  **Upload para S3:** O script Python, usando o SDK `boto3`, faz o upload de cada arquivo de backup individualmente (do banco e dos logs) para o bucket S3, seguindo uma estrutura de pastas organizada por data (`backups/YYYY/MM/DD/`).
6.  **Limpeza:** Após o upload bem-sucedido de todos os arquivos, o script Python remove o diretório temporário local, liberando o espaço em disco do backup recém-criado.
7.  **Log:** Todas as etapas são registradas em um arquivo de log com timestamp, permitindo rastreabilidade e monitoramento do processo.

## 2. Estratégia de Backup Aprimorada (Altamente Recomendada)

A estratégia de backup adotada é robusta, combinando backups full e incrementais com o gerenciamento dos logs de transações (Archived Redo Logs).

* **Backup Full (Nível 0):** Realizado semanalmente. Cria uma cópia completa de todos os datafiles do banco de dados, servindo como a base para os backups incrementais.
* **Backup Incremental (Nível 1):** Realizado diariamente. Faz backup apenas dos blocos de dados que foram alterados desde o último backup de nível 0 ou 1.
* **Backup de Logs Arquivados:** Realizado em cada execução, junto com o backup do banco de dados. Os logs arquivados contêm o registro de todas as transações, sendo essenciais para a recuperação de dados até um ponto exato no tempo.

### Importância da Estratégia para Segurança e Recuperação

Esta estratégia é fundamental por duas razões principais:

1.  **Segurança e Consistência de Dados:** O backup dos logs arquivados garante que, em caso de falha, tenhamos a "fita de vídeo" de todas as transações. Isso permite a recuperação total do banco de dados para um momento exato (Point-in-Time Recovery - PITR), minimizando a perda de dados. Sem os logs, a recuperação ficaria limitada ao momento do último backup incremental, o que poderia resultar em perda de horas de trabalho.

2.  **Eficiência de Armazenamento:** A limpeza automática dos logs arquivados com mais de 24 horas libera espaço em disco no servidor de produção, enquanto a cópia na AWS S3 garante que uma cópia de longo prazo esteja segura e acessível. A retenção local de 24 horas oferece uma camada de segurança extra para recuperações imediatas e rápidas.

## 3. Pré-requisitos e Configurações Obrigatórias

Para que o projeto funcione em um servidor de produção (Linux), as seguintes configurações são essenciais:

### 3.1. Configurações no Banco de Dados Oracle

1.  **Modo ARCHIVELOG:** O banco de dados Oracle deve estar em **`ARCHIVELOG MODE`**, que é mandatório para permitir backups incrementais e a recuperação de ponto no tempo.

2.  **Fast Recovery Area (FRA):** A área de recuperação rápida (`DB_RECOVERY_FILE_DEST`) deve estar configurada e com espaço suficiente para armazenar os logs arquivados temporariamente antes de serem backupados.

### 3.2. Configurações no Servidor Linux

1.  **Instalação do Python e Módulos:**
    * Instalar Python 3.x e o gerenciador de pacotes `pip`.
    * Instalar os módulos Python necessários:
        ```bash
        pip install python-dotenv boto3
        ```

2.  **Variáveis de Ambiente Oracle:**
    * O usuário do sistema que executará o script (`oracle` ou outro) deve ter as variáveis de ambiente `ORACLE_HOME` e `ORACLE_SID` configuradas, e o `$ORACLE_HOME/bin` deve estar no `PATH`.

3.  **Permissões de Acesso ao Banco de Dados:**
    * O usuário do sistema deve ser membro do grupo `dba` (do Oracle) para que o RMAN se conecte via autenticação de sistema (`TARGET /`).

4.  **Credenciais da AWS:**
    * As credenciais da AWS (`AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY`) devem ser salvas de forma segura no arquivo `.env`.

### 3.3. Configuração do Projeto

1.  **Estrutura do Projeto:**
    * A estrutura de diretórios deve ser a seguinte, com as permissões de leitura/escrita garantidas para o usuário do sistema:
        ```
        oracle_backup_s3/
        ├── .env
        ├── backup_oracle_s3.py
        ├── logs/
        └── temp_backups/
        ```
    
2.  **Arquivo `.env`:**
    * Editar o arquivo `.env` com as configurações do ambiente de produção (caminhos, credenciais da AWS, `ORACLE_SID`). A variável `RESTORE_SOURCE_DIR` deve apontar para o diretório onde os arquivos de backup (baixados do S3) estão localizados para o processo de restauração.

### 3.4. Agendamento com Cron

O Cron é a ferramenta ideal para agendar a execução do script.

* **Exemplo de entradas no Crontab (`crontab -e`):**

    ```bash
    # Crontab para o usuário 'oracle'

    # Backup FULL (todo domingo à 1h da manhã)
    0 1 * * 0 /usr/bin/python3 /caminho/para/o/projeto/backup_oracle_s3.py FULL >> /caminho/para/o/projeto/logs/cron_backup.log 2>&1

    # Backup INCREMENTAL (segunda a sábado, à 1h da manhã)
    0 1 * * 1-6 /usr/bin/python3 /caminho/para/o/projeto/backup_oracle_s3.py INCREMENTAL >> /caminho/para/o/projeto/logs/cron_backup.log 2>&1
    ```

## 4. Teste de Implantação

É fundamental realizar um teste manual em produção para validar todo o fluxo, verificando a criação de arquivos de backup e de logs arquivados, o upload para o S3 e a correta limpeza do diretório temporário local.

Este README fornece um guia completo para a implantação, garantindo que a transição do projeto do ambiente de desenvolvimento para produção seja feita de forma segura e eficiente.

## 5. Entendendo a Lógica de Restauração: Um Exemplo Prático

A "mágica" do processo de recuperação está na forma como o RMAN (Recovery Manager) da Oracle utiliza as três peças que o seu script de backup gera:

1.  **Backup Full (Level 0):** Uma cópia completa do seu banco de dados em um ponto no tempo.
2.  **Backup Incremental (Level 1):** Contém apenas os blocos de dados que mudaram desde o último backup (seja ele Full ou outro Incremental). É muito menor e mais rápido que um backup Full.
3.  **Backup de Archived Logs:** São os registros de todas as transações (commits, inserts, updates, deletes) que ocorreram no banco. Eles são o componente chave para a recuperação fina, pois preenchem as lacunas entre os backups.

---

### Cenário Hipotético: Desastre em 02/08 às 15:00

Vamos imaginar a seguinte situação:
- **01/08:** Um backup **FULL** foi executado com sucesso.
- **01/08 e 02/08:** Backups **INCREMENTAIS** foram executados às 20:00, 01:00 e 10:00.
- **02/08 às 15:00:** Ocorreu uma falha crítica no banco de dados.

**Objetivo:** Recuperar o banco de dados para o estado mais próximo possível das 15:00, utilizando o último backup incremental das 10:00 como base.

Veja como o processo de restauração funciona, passo a passo:

#### **Fase 1: Preparação (O papel do `restore_oracle.py`)**

Antes de qualquer coisa, você precisa dos arquivos de backup. Eles estão no S3, mas o RMAN precisa deles em um diretório local.

1.  **Download dos Backups:** O script `restore_oracle.py` é executado. Sua primeira tarefa é se conectar ao S3 e baixar todos os arquivos de backup necessários do bucket `arco-iris`. Com base no nosso cenário, ele precisaria baixar:
    *   O **Backup Full** do dia 01/08.
    *   Todos os **Backups Incrementais** feitos *após* o Full:
        *   O de 01/08 às 20:00.
        *   O de 02/08 às 01:00.
        *   O de 02/08 às 10:00.
    *   Todos os **Backups de Archived Logs** feitos desde o backup Full de 01/08. O script `backup_oracle_s3.py` faz o backup dos archived logs em *todas* as execuções (tanto `FULL` quanto `INCREMENTAL`), o que é uma excelente prática.

2.  **Disponibilização para o RMAN:** Os arquivos baixados seriam colocados em uma pasta local, por exemplo `C:\oracle_backup_s3\temp_restore\`, para que o RMAN possa encontrá-los.

#### **Fase 2: Restauração e Recuperação (A lógica do RMAN)**

Com os arquivos no lugar, o RMAN assume o controle. O processo é notavelmente inteligente e automatizado.

1.  **Passo 1: Restaurar o Backup Full**
    *   Você (ou o script `restore_oracle.py`) se conecta ao RMAN e executa o comando `RESTORE DATABASE;`.
    *   O RMAN identifica que precisa da base, que é o **Backup Full de 01/08**. Ele então restaura os arquivos de dados (datafiles) para o estado em que estavam no dia 01/08.

2.  **Passo 2: Aplicar os Backups Incrementais**
    *   Após restaurar a base, você executa o comando `RECOVER DATABASE;`.
    *   O RMAN consulta seu catálogo e vê que, para avançar no tempo, ele precisa aplicar os backups incrementais. Ele faz isso na ordem correta, aplicando as alterações em sequência.
    *   Ao final deste passo, seu banco de dados está no estado exato das 10:00 do dia 02/08.

3.  **Passo 3: Aplicar os Logs de Transação (Archived Logs)**
    *   Este é o passo que permite a recuperação para um ponto específico no tempo (*Point-in-Time Recovery*). O comando `RECOVER DATABASE;` continua sua execução.
    *   Após aplicar o último incremental (das 10:00), o RMAN começa a aplicar os logs de transação que foram gerados entre as 10:00 e o momento da falha (15:00).
    *   Ele aplicará todas as transações confirmadas até o último log de arquivamento disponível.

4.  **Passo 4: Abrir o Banco de Dados**
    *   Após a recuperação bem-sucedida, o banco de dados não pode ser aberto normalmente. Como você realizou uma recuperação incompleta, você precisa "resetar" a linha do tempo dos logs.
    *   O comando final é `ALTER DATABASE OPEN RESETLOGS;`. Isso abre o banco de dados para uso e inicia uma nova sequência de logs de transação.

Em resumo, o processo é como montar um quebra-cabeça: o RMAN pega a foto grande (Full), adiciona as peças grandes que mudaram (Incrementais) e, por fim, usa as pecinhas minúsculas (Archived Logs) para preencher todos os detalhes até o momento desejado.

## 6. Processo de Restauração

O projeto inclui um script de restauração (`restore_oracle.py`) que utiliza os backups gerados para recuperar o banco de dados. A lógica de restauração foi projetada para recuperar o banco de dados ao seu estado mais recente possível, utilizando os backups `FULL`, `INCREMENTAL` e os `ARCHIVELOGS`.

O script pode ser executado de duas formas: `FULL` e `INCREMENTAL`.

### 5.1. Lógica de Restauração

O objetivo principal do script de restauração é a **recuperação de desastres**, ou seja, restaurar o banco de dados para o estado mais atualizado possível, minimizando a perda de dados. Para isso, ele sempre executa um processo de `RESTORE` seguido por um `RECOVER`.

-   **`RESTORE DATABASE;`**: Restaura os arquivos físicos do banco de dados a partir do backup.
-   **`RECOVER DATABASE;`**: Aplica os backups incrementais e todos os logs de transação (`ARCHIVELOGS`) disponíveis para atualizar o banco de dados até a última transação registrada.

É crucial entender que, por padrão, o script **não** foi feito para "voltar no tempo" para o momento exato de um backup, mas sim para recuperar o máximo de dados.

### 5.2. Modos de Execução

#### a) `python restore_oracle.py FULL`

-   **Como funciona:** Este modo localiza o último backup `FULL`, restaura seus arquivos e, em seguida, aplica **todos os `ARCHIVELOGS`** disponíveis desde que o backup `FULL` foi criado.
-   **Resultado:** O banco de dados é recuperado até a última transação disponível.
-   **Uso:** Funciona perfeitamente, mas pode ser um processo lento se houver um grande volume de transações (muitos `ARCHIVELOGS`) a serem aplicados desde o último backup completo.

#### b) `python restore_oracle.py INCREMENTAL`

-   **Como funciona:** Este modo localiza o último backup `FULL` e também o último backup `INCREMENTAL`. O RMAN, de forma inteligente, restaura o `FULL`, aplica o `INCREMENTAL` (que consolida muitas mudanças de forma rápida) e, por fim, aplica apenas os `ARCHIVELOGS` gerados *após* o backup incremental.
-   **Resultado:** O mesmo que o modo `FULL` – o banco de dados é recuperado até a última transação disponível.
-   **Uso:** Este é o método **preferencial e mais eficiente** para recuperação. A aplicação de um único backup incremental é significativamente mais rápida do que processar dias de `ARCHIVELOGS` individuais, otimizando drasticamente o tempo de recuperação (RTO - Recovery Time Objective).