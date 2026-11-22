import { db, isCloudSqlConfigured } from './index.ts';
import { users } from './schema.ts';

export async function getOrCreateUser(
  uid: string,
  email: string,
  displayName?: string | null
) {
  if (!isCloudSqlConfigured()) {
    return null;
  }
  try {
    const result = await db
      .insert(users)
      .values({
        uid,
        email,
        displayName: displayName ?? null,
        updatedAt: new Date(),
      })
      .onConflictDoUpdate({
        target: users.uid,
        set: {
          email,
          displayName: displayName ?? null,
          updatedAt: new Date(),
        },
      })
      .returning();

    return result[0] ?? null;
  } catch (error) {
    console.error('Database user upsert failed:', error);
    throw new Error('Unable to synchronize user profile.', { cause: error });
  }
}
