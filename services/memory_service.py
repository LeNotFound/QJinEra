from services.storage import storage
from services.llm import llm_service
from typing import List, Dict, Any

class MemoryService:
    async def consolidate_if_needed(self, user_id: str, group_id: str):
        """
        Check if user has enough active memories to trigger consolidation.
        If yes, call LLM to merge facts into description.
        """
        try:
            # 1. Get active memories
            active_mem = storage.get_active_memories_details(user_id)
            
            # Threshold check (configurable? hardcoded to 3 for now per PRD)
            if len(active_mem) < 3:
                return 

            print(f"[MemoryService] Triggering consolidation for user {user_id} (Facts: {len(active_mem)})")

            # 2. Prune expired short-term memories first
            storage.prune_short_term_memories(retention_hours=24)

            # 3. Get user profile
            user = storage.get_user(group_id, user_id)
            current_desc = user["description"] if user else ""
            if not current_desc:
                current_desc = "New user."

            # 4. Call LLM
            # This is a slow operation, run in background
            result = await llm_service.consolidate_memory(current_desc, active_mem)
            
            # 5. Update DB
            if result:
                new_desc = result.get("new_description")
                consolidated_ids = result.get("consolidated_ids", [])
                discarded_ids = result.get("discarded_ids", [])
                
                if new_desc:
                    storage.update_user_description(group_id, user_id, new_desc)
                    print(f"[MemoryService] ✅ Updated description for {user_id}")
                
                # Batch 1: Consolidated -> Archived
                valid_cons_ids = [int(i) for i in consolidated_ids if isinstance(i, (int, str)) and str(i).isdigit()]
                if valid_cons_ids:
                    storage.update_memories_status(valid_cons_ids, "archived")
                    print(f"[MemoryService] 🗄️ Archived {len(valid_cons_ids)} consolidated facts")

                # Batch 2: Discarded -> Short Term
                valid_disc_ids = [int(i) for i in discarded_ids if isinstance(i, (int, str)) and str(i).isdigit()]
                if valid_disc_ids:
                    storage.update_memories_status(valid_disc_ids, "short_term")
                    print(f"[MemoryService] 🕰️ Moved {len(valid_disc_ids)} facts to short-term storage")

                # Note: keep_active_ids are naturally ignored as their status remains 'active'

        except Exception as e:
            print(f"[MemoryService] Error during consolidation: {e}")

memory_service = MemoryService()
