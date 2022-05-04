import numpy as np
from pathlib import Path
import os
import time
import datetime
import SimpleITK as sitk
from typing import List
from get_config import get_config_dict
from PIL import Image


def get_unique_image_file(subject_protocol_folder: List[Path]) -> np.array:
    # the inversion [::-1] is done so the most preprocessed data is used
    found_image_ids = np.array([image_file.parents[0].name for image_file in subject_protocol_folder])
    inverse_found_image_ids = found_image_ids[::-1]
    ids, idx = np.unique(inverse_found_image_ids, return_index=True)
    unique_image_ids_paths = np.array(subject_protocol_folder)[::-1][idx]

    assert len(unique_image_ids_paths) <= len(subject_protocol_folder)
    assert len(unique_image_ids_paths) > 0

    return unique_image_ids_paths


def intensity_normalization(volume: np.array, clip_ratio: float = 99.5):
    # Normalize the pixel values of volumes to (-1, 1)
    assert np.min(volume) == 0.0
    volume_max = np.percentile(volume, clip_ratio)
    volume = np.clip(volume / volume_max, 0, 1) * 2 - 1

    return volume


def run_fsl_processing(image_path: Path, preprocessed_image_path: Path, ref: Path):
    os.system(f'fslreorient2std {image_path} {preprocessed_image_path}')
    os.system(f'robustfov -i {preprocessed_image_path} -r {preprocessed_image_path}')
    os.system(f'bet {preprocessed_image_path} {preprocessed_image_path} -R')
    os.system(f'flirt -in {preprocessed_image_path} -ref {ref} -out {preprocessed_image_path}')
    # "fast" saves output file as {file_name}_restore.nii.gz
    os.system(f'fast --nopve -B -o {preprocessed_image_path} {preprocessed_image_path}')
    preprocessed_image_path_fsl = Path(str(preprocessed_image_path).replace(".nii", "_restore.nii"))
    return preprocessed_image_path_fsl


def load_np_image(preprocessed_image_path: Path) -> np.array:
    ## load image
    preprocessed_image_sitk = sitk.ReadImage(str(preprocessed_image_path))
    preprocessed_image_np = sitk.GetArrayFromImage(preprocessed_image_sitk)
    return preprocessed_image_np


def cropping(image: np.array, axial_size: int = 90, central_crop_along_z: bool = True):
    init_shape = image.shape
    cropped_image = image
    if axial_size is not None:
        cropped_image = cropped_image[:,
                        init_shape[1] // 2 - axial_size // 2:init_shape[1] // 2 + axial_size // 2,
                        init_shape[2] // 2 - axial_size // 2:init_shape[2] // 2 + axial_size // 2]
    if central_crop_along_z:
        cropped_image = cropped_image[30:60, ...]

    return cropped_image


def save_np(image_np, preprocessed_image_path):
    # preprocessed_image_path = preprocessed_image_path[:preprocessed_image_path.rfind(".")]
    preprocessed_image_path = str(preprocessed_image_path).replace(".nii.gz", "")

    data_dict = {"image": image_np}
    np.savez_compressed(preprocessed_image_path, data_dict)  # saving into .npz


def save_2d(image_np, preprocessed_image_path):
    # preprocessed_image_path = str(preprocessed_image_path)[:str(preprocessed_image_path).rfind(".")]
    new_preprocessed_image_path = str(preprocessed_image_path).replace(".nii.gz", "")
    for slice in range(image_np.shape[0]):
        Image.fromarray(image_np[slice]).save(new_preprocessed_image_path + f"_slice{slice}.tiff")


def remove_nii_files(path: Path):
    for file in path.parent.glob('**/*.nii*'):
        file.unlink()


def main():
    total_start = time.time()

    config = get_config_dict()

    subject_folder_list = sorted(list(config["data_path"].glob('*')))
    # subjects_list = [subject_folder.name for subject_folder in subject_folder_list]
    nb_subjects = len(subject_folder_list)
    nb_images = 0
    for subject_nb, subject_folder in enumerate(subject_folder_list):
        subject_image_files = sorted(subject_folder.glob("**/*.nii"))
        subject_image_files_unique = get_unique_image_file(subject_image_files)

        nb_images += subject_image_files_unique.shape[0]

        for image_nb, image_path in enumerate(subject_image_files_unique):
            preprocessed_image_path = Path(
                str(image_path).replace("raw", "preprocessed").replace(".nii", ".nii.gz"))
            preprocessed_image_path.parent.mkdir(parents=True, exist_ok=True)

            nb_processed_files = len(list(preprocessed_image_path.parent.glob("**/*.tiff")))
            if nb_processed_files > 0 and not config["re_process"]:
                continue

            start = time.time()
            try:
                preprocessed_image_path_fsl = run_fsl_processing(image_path, preprocessed_image_path,
                                                                 config["reference_atlas_location"])
                preprocessed_image_np = load_np_image(preprocessed_image_path_fsl)
            except:
                with open('load_error_list.txt', 'a') as the_file:
                    the_file.write(f'{str(image_path)}\n')
                continue

            normalized_image_np = intensity_normalization(preprocessed_image_np)

            if config["axial_size"] is not None:
                cropped_normalized_image_np = cropping(normalized_image_np, axial_size=config["axial_size"])
            if config["save_2d"]:
                save_2d(cropped_normalized_image_np, preprocessed_image_path)
            else:
                save_np(cropped_normalized_image_np, preprocessed_image_path)

            remove_nii_files(preprocessed_image_path)

            print(
                f' Subject {subject_nb}; Image {image_nb}, '
                f'processing time: {datetime.timedelta(seconds=time.time() - start)}')
            print(f" Subject {subject_folder.name}, image {preprocessed_image_path.parent.name}")

    print(f'Total processing time: {datetime.timedelta(seconds=time.time() - total_start)}')


if __name__ == "__main__":
    main()