import pybinding
import bin_packer
import time

# print("pybinding Item:", pybinding.Item('Item 1', 15., 5., 5., [pybinding.RotationType.whd], "red"))
# print("pybinding Bin:", pybinding.Bin('Le grande box', 10000000., 10000000., 30000000.))
# print("pybinding Packer instance:", pybinding.Packer())

packer = pybinding.Packer()
packer.add_bin(pybinding.Bin('Le grande box', 2500, 2650, 13600))
for i in range(80):
    packer.add_item(pybinding.Item(f'Bag {i}', 500, 400, 300))
for i in range(100):
    packer.add_item(pybinding.Item(f'Sack {i}', 1000, 450, 300))
for i in range(150):
    packer.add_item(pybinding.Item(f'Box {i}', 1000, 1000, 1000))

start = time.time()
packer.pack()
print("Time taken:", time.time() - start)

print("packed bins:", packer.get_bins())
print("unfit items:", packer.get_unfit_items(), len(packer.get_unfit_items()))
print("all items:", packer.get_items())
for bin_ in packer.get_bins():
    print("items in bin:", bin_.get_items(), len(bin_.get_items()))
    for i, item in enumerate(bin_.get_items()):

        # print("item position:", item.get_position(), type(item.get_position()))
        print("item position", i, item.name, item.get_position())

        # print("item binary representation:", [bin(i) for i in item._position])
        # print("item position:", item.get_pos(), type(item.get_pos()))

        # print("item position:", int(item.get_position()[0]), int(item.get_position()[1]), int(item.get_position()[2]))

        # print("item rotation type:", item.get_rotation_type(), type(item.get_rotation_type()))
        # print("item dimension:", item.get_dimension(), type(item.get_dimension()))

print()
# packer = bin_packer.Packer()
# packer.add_bin(bin_packer.Bin('Le grande box', 2500, 2650, 13600))
# for i in range(160):
#     packer.add_item(bin_packer.Item(f'Item {i}', 500, 400, 300))
# for i in range(200):
#     packer.add_item(bin_packer.Item(f'Item {i}', 1000, 450, 300))
# for i in range(20):
#     packer.add_item(bin_packer.Item(f'Item {i}', 1000, 1000, 1000))

# start = time.time()
# packer.pack()

# print("Time taken:", time.time() - start)
# print("packed bins:", packer.bins)
# print("unfit items:", packer.unfit_items, len(packer.unfit_items))
# print("all items:", packer.items)
# for bin_ in packer.bins:
#     print("items in bin:", bin_.items, len(bin_.items))
    # for item in bin_.items:
    #     print("item position:", item.position, type(item.position))
        # print("item attrs", item._position)
        # print("item binary representation:", [bin(i) for i in item._position])
        # print("item position:", item.get_pos(), type(item.get_pos()))

        # print("item position:", int(item.position[0]), int(item.position[1]), int(item.position[2]))

        # print("item rotation type:", item.rotation_type, type(item.rotation_type))
        # print("item dimension:", item.dimension, type(item.dimension))
