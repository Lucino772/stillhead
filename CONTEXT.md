# Words

Each word has one meaning in this project. Use these words, and only with these meanings.

| Word | Meaning |
| --- | --- |
| **module** | A set of tables that belong together, with the revisions that build them. |
| **prefix** | The start of the name of each table that a module owns. The default is the module name and an underscore. |
| **own** | A module owns a table when the table name starts with the prefix of the module. |
| **namespace** | All the tables that a module owns. |
| **revision** | One migration file in the `versions/` directory of a module. |
| **head** | The newest revision in the `versions/` directory. |
| **version table** | The table where the database records the stamp of a module. One for each module. |
| **stamp** | The revision that the version table records. |
| **pending** | The revisions after the stamp, up to head. |
| **valid** | Accepted by validation. Only a valid module can be migrated. |
| **module set** | The modules that share one database and one schema. |
| **schema** | The Postgres schema of a connection. A module never has a schema. |
| **build** | One version of your application, with the revisions that it contains. |

## Words not to use

| Do not use | Use |
| --- | --- |
| descriptor | module |
| deployment | module set |
| lineage, chain | revisions |
| marker, ownership marker | prefix |
| boundary | "the tables that a module owns" |
| façade | "the `stillhead` package" |
