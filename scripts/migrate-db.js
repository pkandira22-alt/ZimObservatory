import 'dotenv/config';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import { createPool, db, isCloudSqlConfigured } from '../src/db/index.ts';
import { fileURLToPath } from 'node:url';

if (!isCloudSqlConfigured()) {
  throw new Error('SQL_HOST, SQL_USER, SQL_PASSWORD and SQL_DB_NAME are required to run migrations.');
}

try {
  await migrate(db, { migrationsFolder: fileURLToPath(new URL('../drizzle', import.meta.url)) });
  console.log('PostgreSQL migrations completed.');
} finally {
  await createPool().end();
}
