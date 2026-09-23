from obj6502 import ObjectCode

def output_obj(objcode: ObjectCode) -> None:
    # Create map of label_num => label str
    label_name_to_num = {}
    for label_name, label_num in objcode.labels.items():
        label_name_to_num[label_num[0]] = label_name

    for idx, bs in enumerate(objcode.code_bytes):
        if idx in label_name_to_num:
            print(f"{label_name_to_num[idx]}:")
        b_str = " ".join([f"{x:02X}" for x in bs])
        if idx in objcode.offsets_to_resolve:
            b_str += f" {objcode.offsets_to_resolve[idx]}"
        print(f"\t{b_str}")

