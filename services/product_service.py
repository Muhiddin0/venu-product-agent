"""Product generation service layer."""

import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pandas as pd

from agent import generate_product_text, select_category_brand
from agent.category_brand.schemas import CategoryBrandSelectionSchema
from agent.product.schemas import ProductGenSchema
from api import VenuSellerAPI
from core.config import settings
from core.constants import DEFAULT_FALLBACK_IMAGE

logger = logging.getLogger(__name__)


class ProductServiceError(Exception):
    """Base exception for product service errors."""

    pass


class ShopSaveError(ProductServiceError):
    """Raised when saving to shop fails."""

    pass


def get_default_image_path() -> str:
    """
    Get default image path for products.

    Returns:
        str: Path to default image file
    """
    if os.path.exists(DEFAULT_FALLBACK_IMAGE):
        return DEFAULT_FALLBACK_IMAGE

    # Create media/products directory if it doesn't exist
    media_dir = Path("media/products")
    media_dir.mkdir(parents=True, exist_ok=True)

    # Return default path (will be created if needed)
    default_path = str(media_dir / "default_product.png")
    logger.info(f"Using default image path: {default_path}")
    return default_path


class ProductService:
    """Service for product generation and shop integration."""

    def __init__(self):
        """Initialize product service."""
        self._venu_api: Optional[VenuSellerAPI] = None

    def _get_venu_api(self) -> VenuSellerAPI:
        """
        Get or create Venu API client.

        Returns:
            VenuSellerAPI: Authenticated API client

        Raises:
            ShopSaveError: If credentials are missing or login fails
        """
        if not settings.venu_email or not settings.venu_password:
            raise ShopSaveError(
                "VENU_EMAIL yoki VENU_PASSWORD sozlanganmagan. "
                "Do'konga saqlash o'tkazib yuborildi."
            )

        if self._venu_api is None:
            self._venu_api = VenuSellerAPI(
                email=settings.venu_email, password=settings.venu_password
            )

            if not self._venu_api.login():
                raise ShopSaveError("Venu API ga login qilishda xatolik")

        return self._venu_api

    def _get_mxik_codes(
        self, 
        sub_sub_category_id: Optional[Any] = None
    ) -> Tuple[Any, Any]:
        """
        Get MXIK and package codes from Excel file.
        Tries sub_sub_sub_category_id first, then falls back to sub_sub_category_id.

        Args:
            sub_sub_sub_category_id: Sub-sub-sub-category ID to look up (takes priority)

        Returns:
            Tuple[any, any]: (mxik_code, package_code) - can be int or str
        """
        default_mxik = 0
        default_package = 0

        # Try sub_sub_sub_category_id first if available
        if sub_sub_category_id is None:
            logger.info("Sub-sub-category ID not provided")
            return default_mxik, default_package

        print(f"Looking up codes for sub-sub-category ID: {sub_sub_category_id}")

        try:
            excel_path = Path("api/mxik-codes.xlsx")
            df = pd.read_excel(excel_path, header=None)
            
            # Convert sub_sub_category_id to int for comparison (Excel column is numeric)
            try:
                search_id = int(sub_sub_category_id) if sub_sub_category_id is not None else None
            except (ValueError, TypeError):
                search_id = sub_sub_category_id
            
            # Convert Excel column 0 to numeric for proper comparison
            df[0] = pd.to_numeric(df[0], errors='coerce')
            
            match = df[df[0] == search_id]
            if not match.empty:
                mxik = match.iloc[0, 2]
                package_code = match.iloc[0, 3]
                try:
                    if pd.notna(mxik):
                        mxik = int(mxik)
                    if pd.notna(package_code):
                        package_code = int(package_code)
                except:
                    pass
                return mxik, package_code
            return default_mxik, default_package

        except Exception as e:
            logger.error(f"Error reading MXIK codes from Excel: {e}")
            return default_mxik, default_package

    def generate_product_content(
        self, name: str, brand: str, price: int, stock: int
    ) -> ProductGenSchema:
        """
        Generate product text content using AI.

        Args:
            name: Product name
            brand: Product brand
            price: Product price
            stock: Product stock

        Returns:
            ProductGenSchema: Generated product content
        """
        logger.info(f"Generating product content: {name} ({brand})")
        return generate_product_text(name=name, brand=brand, price=price, stock=stock)

    def get_product_images(
        self,
        product_name: str,
        brand: str,
        max_images: int = 5,
    ) -> List[str]:
        """
        Get default product images.

        Args:
            product_name: Name of the product
            brand: Brand of the product
            max_images: Maximum number of images to return (max 5)

        Returns:
            List[str]: List of paths to default image files
        """
        logger.info(f"Using default images for: {product_name} ({brand})")
        default_image = get_default_image_path()
        return [default_image] * min(max_images, 5)

    def save_product_to_shop(
        self,
        product: ProductGenSchema,
        category_selection: CategoryBrandSelectionSchema,
        main_image_path: str,
        additional_images_paths: List[str],
        api_client: Optional[VenuSellerAPI] = None,
        product_params: Optional[dict] = None,
        price: int = 0,
        stock: int = 5,
    ) -> Tuple[bool, dict]:
        """
        Save product to shop via Venu API.

        Args:
            product: ProductGenSchema instance
            category_selection: CategoryBrandSelectionSchema instance
            main_image_path: Path to main image
            additional_images_paths: List of additional image paths
            api_client: Optional VenuSellerAPI client (overrides default)
            product_params: Optional dict with weight, height, width, length

        Returns:
            Tuple[bool, dict]: (success, response) - success status and API response
        """
        try:
            venu_api = api_client if api_client else self._get_venu_api()

            logger.info("Do'konga mahsulotni saqlash boshlandi...")

            # Extract product dimensions from product_params if available
            weight = 1
            height = 1
            width = 1
            length = 1
            if product_params:
                weight = product_params.get("weight", 1)
                height = product_params.get("height", 1)
                width = product_params.get("width", 1)
                length = product_params.get("length", 1)

            # Get MXIK and package codes from Excel
            # Try sub_sub_sub_category_id first, fallback to sub_sub_category_id
            mxik, package_code = self._get_mxik_codes(
                sub_sub_category_id=category_selection.sub_sub_category_id
            )

            # Add product to shop
            result = venu_api.add_product(
                name_ru=product.name_ru,
                name_uz=product.name_uz,
                description_ru=product.description_ru,
                description_uz=product.description_uz,
                meta_image=main_image_path,
                meta_title=product.meta_title + " " + "Toshkentda sotib olish",
                meta_description=product.meta_description + " " + "Toshkentda sotib olish",
                tags=product.tags,
                price=price,
                brand_id=category_selection.brand_id,
                main_image_path=main_image_path,
                additional_images_paths=additional_images_paths,
                stock=stock,
                category_id=category_selection.category_id,
                sub_category_id=category_selection.sub_category_id,
                sub_sub_category_id=category_selection.sub_sub_category_id,
                weight=weight,
                height=height,
                width=width,
                length=length,
                mxik=mxik,
                package_code=package_code,
            )

            # Check result
            if result.get("status") == "error" or result.get("error"):
                logger.error(f"Do'konga saqlashda xatolik: {result}")
                return False, result

            logger.info(f"Mahsulot muvaffaqiyatli do'konga saqlandi: {product.name_ru}")
            
            # Clean up downloaded images
            for image_path in additional_images_paths:
                if os.path.exists(image_path):
                    os.remove(image_path)
                    logger.info(f"Rasm o'chirildi: {image_path}")
                else:
                    logger.warning(f"Rasm topilmadi: {image_path}")

            # Clean up broken images and update status
            try:
                product_id = result.get("request", {}).get("id")
                if product_id:
                    # Clean up broken images (path is null and status is 404)
                    logger.info(f"Rasmlarni tekshiryapman va buzilgan rasmlarni olib tashlayapman (product_id: {product_id})...")
                    removed_count = venu_api.cleanup_broken_images(product_id)
                    if removed_count > 0:
                        logger.info(f"{removed_count} ta buzilgan rasm olib tashlandi (product_id: {product_id})")
                    else:
                        logger.info(f"Buzilgan rasm topilmadi (product_id: {product_id})")
                    
                    # Update product status to 1
                    logger.info(f"Mahsulot statusini yangilayapman (product_id: {product_id}, status: 1)...")
                    if venu_api.update_product_status(product_id, status=1):
                        logger.info(f"Mahsulot statusi muvaffaqiyatli yangilandi (product_id: {product_id}, status: 1)")
                    else:
                        logger.warning(f"Mahsulot statusini yangilashda xatolik (product_id: {product_id})")
                else:
                    logger.warning(f"Product ID topilmadi, rasmlarni tozalash va status yangilash o'tkazib yuborildi. Response: {result}")
            except Exception as e:
                # Cleanup and status update failures should not affect product creation success
                logger.warning(f"Rasmlarni tozalash yoki status yangilashda xatolik (product yaratilgan): {e}")
            
            return True, result

        except ShopSaveError as e:
            logger.error(f"Do'konga saqlashda xatolik: {e}")
            return False, {"error": str(e)}
        except Exception as e:
            logger.error(f"Do'konga saqlashda kutilmagan xatolik: {e}", exc_info=True)
            return False, {"error": str(e)}

    def select_category_and_brand(
        self,
        product_name: str,
        brand_name: str,
        api_client: Optional[VenuSellerAPI] = None,
    ) -> Tuple[bool, Optional[dict], Optional[CategoryBrandSelectionSchema]]:
        """
        Select category and brand using AI.

        Args:
            product_name: Product name
            brand_name: Brand name
            api_client: Optional VenuSellerAPI client (overrides default)

        Returns:
            Tuple[bool, Optional[dict], Optional]: (success, error_dict, category_selection)
        """
        try:
            venu_api = api_client if api_client else self._get_venu_api()

            # Get categories and brands
            logger.info("Kategoriya va brendlarni yuklayapman...")
            categories = venu_api.get_categories()
            brands = venu_api.get_brands()

            if not categories or not brands:
                error_msg = "Kategoriya yoki brendlar yuklanmadi"
                logger.error(error_msg)
                return False, {"error": error_msg}, None

            # AI yordamida kategoriya va brand ni aniqlash
            logger.info(
                f"AI yordamida kategoriya va brand ni aniqlayapman: "
                f"{product_name} ({brand_name})"
            )
            category_selection = select_category_brand(
                product_name=product_name,
                brand_name=brand_name,
                categories=categories,
                brands=brands,
            )

            logger.info(
                f"Aniqlangan: category_id={category_selection.category_id}, "
                f"sub_category_id={category_selection.sub_category_id}, "
                f"sub_sub_category_id={category_selection.sub_sub_category_id}, "
                f"brand_id={category_selection.brand_id}"
            )

            return True, None, category_selection

        except ShopSaveError as e:
            logger.error(f"Kategoriya va brand aniqlashda xatolik: {e}")
            return False, {"error": str(e)}, None
        except Exception as e:
            logger.error(
                f"Kategoriya va brand aniqlashda kutilmagan xatolik: {e}", exc_info=True
            )
            return False, {"error": str(e)}, None
