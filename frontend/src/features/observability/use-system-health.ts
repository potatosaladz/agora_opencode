import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../api/client";

export function useSystemHealth() {
  const liveness = useQuery({
    queryKey: ["system", "liveness"],
    queryFn: ({ signal }) => apiClient.getHealth(signal),
  });
  const readiness = useQuery({
    queryKey: ["system", "readiness"],
    queryFn: ({ signal }) => apiClient.getReadiness(signal),
  });

  return { liveness, readiness };
}
