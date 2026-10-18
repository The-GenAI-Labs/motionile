"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateProduct,
  createProduct,
  deactivateProduct,
  duplicateProduct,
  getProduct,
  listProducts,
  syncProductPlan,
  updateProduct,
} from "@/features/admin-billing/api/admin-billing.api";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import type {
  AdminProductDetail,
  ProductFilters,
} from "@/features/admin-billing/types/admin-billing.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

export type ProductAction = "activate" | "deactivate" | "sync-plan";

const productActions = {
  activate: activateProduct,
  deactivate: deactivateProduct,
  "sync-plan": syncProductPlan,
} as const satisfies Record<ProductAction, (productId: string) => Promise<AdminProductDetail>>;

export const useAdminProducts = (filters: ProductFilters) =>
  useCursorList(adminBillingKeys.productList(filters), (cursor) => listProducts(filters, cursor));

export const useAdminProduct = (productId: string) =>
  useQuery({
    queryKey: adminBillingKeys.product(productId),
    queryFn: () => getProduct(productId),
  });

export const useCreateProduct = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createProduct,
    onSuccess: (product) => {
      client.setQueryData(adminBillingKeys.product(product.id), product);
      return client.invalidateQueries({ queryKey: adminBillingKeys.products() });
    },
  });
};

export const useUpdateProduct = (productId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: Parameters<typeof updateProduct>[1]) => updateProduct(productId, input),
    onSuccess: (product) => {
      client.setQueryData(adminBillingKeys.product(productId), product);
      return client.invalidateQueries({ queryKey: adminBillingKeys.products() });
    },
  });
};

export const useDuplicateProduct = (productId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (overrides: Parameters<typeof duplicateProduct>[1]) =>
      duplicateProduct(productId, overrides),
    onSuccess: (product) => {
      client.setQueryData(adminBillingKeys.product(product.id), product);
      return client.invalidateQueries({ queryKey: adminBillingKeys.products() });
    },
  });
};

export const useProductAction = (productId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: ProductAction) => productActions[action](productId),
    onSuccess: (product) => {
      client.setQueryData(adminBillingKeys.product(productId), product);
      return client.invalidateQueries({ queryKey: adminBillingKeys.products() });
    },
  });
};
